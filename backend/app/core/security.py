import hashlib
import hmac
import secrets
import string
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pyotp
import structlog
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()
_logger = structlog.get_logger()

# DITSALA Code rules — docs/DITSALA_MASTER_SPEC.md §15.
MIN_CODE_LENGTH = 8

HIBP_PWNED_PASSWORDS_URL = "https://api.pwnedpasswords.com/range/"


def hash_secret(secret: str) -> str:
    """Argon2id — used for both the DITSALA Code (§15) and email
    verification codes (§10); the latter are short-lived and rate-limited
    at the domain layer, but there's no reason to hash them any less
    carefully than a real credential."""
    return _hasher.hash(secret)


def verify_secret(hash_: str, secret: str) -> bool:
    try:
        return _hasher.verify(hash_, secret)
    except VerifyMismatchError:
        return False


def hash_national_id(national_id: str, *, pepper: str) -> str:
    """
    Deterministic (HMAC-SHA256, keyed by a server-side pepper), unlike
    Argon2id — `users.national_id_hash` has a uniqueness constraint to
    catch duplicate signups, which a salted/non-deterministic hash could
    never support (Argon2id is right for the DITSALA Code and email codes,
    which we only ever verify, never compare for equality across rows).
    """
    return hmac.new(pepper.encode(), national_id.encode(), hashlib.sha256).hexdigest()


def validate_ditsala_code_strength(code: str) -> bool:
    return len(code) >= MIN_CODE_LENGTH and any(char.isdigit() for char in code)


PIN_LENGTH = 6
_COMMON_WEAK_PINS = frozenset(
    {"000000", "111111", "222222", "333333", "444444", "555555", "666666",
     "777777", "888888", "999999", "123456", "654321", "123123", "112233",
     "121212", "010203", "202020"}
)  # fmt: skip


def validate_pin_strength(pin: str) -> bool:
    """ADR 0014 — normal-tier accounts use a 6-digit PIN instead of the
    original alphanumeric DITSALA Code; VIP keeps that original rule
    (`validate_ditsala_code_strength`) unchanged."""
    return len(pin) == PIN_LENGTH and pin.isdigit()


def is_weak_pin(pin: str) -> bool:
    """The numeric-PIN equivalent of `is_breached_code`'s HIBP check —
    a 6-digit space is too small for a breach-corpus lookup to say much,
    so this instead rejects the patterns real PIN attackers try first:
    every digit the same, a purely sequential run, and a short blocklist
    of common picks."""
    if pin in _COMMON_WEAK_PINS:
        return True
    digits = [int(d) for d in pin]
    ascending = all(b - a == 1 for a, b in zip(digits, digits[1:], strict=False))
    descending = all(a - b == 1 for a, b in zip(digits, digits[1:], strict=False))
    return ascending or descending


async def is_breached_code(code: str) -> bool:
    """
    §15 breach-corpus check, via Have I Been Pwned's Pwned Passwords
    k-anonymity API — the only acceptable approach for checking a
    not-yet-hashed secret against a third party: only a 5-character SHA-1
    prefix ever leaves this process, never the code itself, and HIBP
    can't feasibly reverse the remaining suffix space back to it.

    Fails open (returns False) on any network/API problem — signup and
    account recovery must not become unavailable because a third-party
    lookup timed out. The structural check
    (`validate_ditsala_code_strength`) is enforced unconditionally
    either way; this is an additional check layered on top of it, not a
    replacement.
    """
    digest = hashlib.sha1(code.encode()).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{HIBP_PWNED_PASSWORDS_URL}{prefix}")
            response.raise_for_status()
    except httpx.HTTPError:
        await _logger.awarning("hibp_breach_check_unavailable")
        return False
    return any(line.split(":")[0] == suffix for line in response.text.splitlines())


def generate_numeric_code(length: int = 6) -> str:
    """Cryptographically random — used for email verification codes (§10).
    Phone codes are Twilio Verify's own, never generated here."""
    return "".join(secrets.choice(string.digits) for _ in range(length))


_INVITE_CODE_ALPHABET = string.ascii_uppercase + string.digits


def generate_invite_code(length: int = 10) -> str:
    """§22 invitation codes — single-use, time-bounded. Uppercase+digits
    only (no lowercase) so it reads unambiguously off a shared screen."""
    return "".join(secrets.choice(_INVITE_CODE_ALPHABET) for _ in range(length))


ONBOARDING_TOKEN_TTL_HOURS = 2
_ONBOARDING_TOKEN_TYPE = "onboarding"


def create_onboarding_token(user_id: uuid.UUID, *, jwt_secret: str) -> str:
    """
    Signup returns this instead of the raw user id, and every subsequent
    onboarding call requires it. A pre-authentication user id in a URL is
    an IDOR waiting to happen (anyone who learns another signup's UUID
    could confirm codes, submit KYC, etc. for them) — this token is the
    minimum viable session for the phase of the flow that happens before
    a full session exists (§16-17 own that).
    """
    payload = {
        "sub": str(user_id),
        "type": _ONBOARDING_TOKEN_TYPE,
        "exp": datetime.now(UTC) + timedelta(hours=ONBOARDING_TOKEN_TTL_HOURS),
    }
    return jwt.encode(payload, jwt_secret, algorithm="HS256")


def decode_onboarding_token(token: str, *, jwt_secret: str) -> uuid.UUID:
    """Raises jwt.InvalidTokenError (or a subclass) on anything wrong —
    expired, wrong type, bad signature. Callers turn that into a 401."""
    payload = jwt.decode(token, jwt_secret, algorithms=["HS256"])
    if payload.get("type") != _ONBOARDING_TOKEN_TYPE:
        raise jwt.InvalidTokenError("Not an onboarding token.")
    return uuid.UUID(payload["sub"])


# --- §16-17: sessions, devices, two-factor login ---

ACCESS_TOKEN_TYPE = "access"
_LOGIN_TOKEN_TYPE = "login"
LOGIN_TOKEN_TTL_MINUTES = 15


def generate_refresh_token() -> str:
    """High-entropy opaque token — not a JWT. Hashed before storage
    (below); the plaintext exists only in this response and on the
    device's SecureStore."""
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    """Deterministic (SHA-256, no salt/pepper needed) — this is a lookup
    key for a 256-bit random value, not a low-entropy secret a human
    chose, so it doesn't need Argon2id's slow-hash properties. Unlike
    `hash_national_id`, there's no PII here worth extra key separation."""
    return hashlib.sha256(token.encode()).hexdigest()


def create_access_token(
    user_id: uuid.UUID, device_id: uuid.UUID, *, jwt_secret: str, ttl_minutes: int
) -> str:
    payload = {
        "sub": str(user_id),
        "device_id": str(device_id),
        "type": ACCESS_TOKEN_TYPE,
        "exp": datetime.now(UTC) + timedelta(minutes=ttl_minutes),
    }
    return jwt.encode(payload, jwt_secret, algorithm="HS256")


@dataclass(frozen=True)
class AccessTokenPayload:
    user_id: uuid.UUID
    device_id: uuid.UUID


def decode_access_token(token: str, *, jwt_secret: str) -> AccessTokenPayload:
    payload = jwt.decode(token, jwt_secret, algorithms=["HS256"])
    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise jwt.InvalidTokenError("Not an access token.")
    return AccessTokenPayload(
        user_id=uuid.UUID(payload["sub"]), device_id=uuid.UUID(payload["device_id"])
    )


@dataclass(frozen=True)
class LoginTokenPayload:
    """
    Carries the device details from /auth/login/start through to
    /auth/login/complete — the device row isn't created until the liveness
    check actually passes, so there's nowhere else to hold them between
    the two calls except this token's claims.
    """

    user_id: uuid.UUID
    job_id: str
    device_name: str
    platform: str
    push_token: str | None


def create_login_token(payload: LoginTokenPayload, *, jwt_secret: str) -> str:
    claims = {
        "sub": str(payload.user_id),
        "type": _LOGIN_TOKEN_TYPE,
        "job_id": payload.job_id,
        "device_name": payload.device_name,
        "platform": payload.platform,
        "push_token": payload.push_token,
        "exp": datetime.now(UTC) + timedelta(minutes=LOGIN_TOKEN_TTL_MINUTES),
    }
    return jwt.encode(claims, jwt_secret, algorithm="HS256")


def decode_login_token(token: str, *, jwt_secret: str) -> LoginTokenPayload:
    claims = jwt.decode(token, jwt_secret, algorithms=["HS256"])
    if claims.get("type") != _LOGIN_TOKEN_TYPE:
        raise jwt.InvalidTokenError("Not a login token.")
    return LoginTokenPayload(
        user_id=uuid.UUID(claims["sub"]),
        job_id=claims["job_id"],
        device_name=claims["device_name"],
        platform=claims["platform"],
        push_token=claims["push_token"],
    )


# --- §28-29: admin panel auth (TOTP MFA) ---
#
# Distinct token `type` claims from the user-facing tokens above, signed
# with the same `jwt_secret` — the `type` check in each decode function is
# what stops an admin token and a user token from ever being interchangeable,
# not a separate key (a separate signing key would be stronger key
# separation but wasn't judged necessary given admin panel access is
# already gated by TOTP MFA + RBAC on top of this).

ADMIN_MFA_ENROLL_TOKEN_TYPE = "admin_mfa_enroll"
ADMIN_LOGIN_TOKEN_TYPE = "admin_login"
ADMIN_ACCESS_TOKEN_TYPE = "admin_access"
ADMIN_MFA_TOKEN_TTL_MINUTES = 10
ADMIN_LOGIN_TOKEN_TTL_MINUTES = 10


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def totp_provisioning_uri(*, secret: str, email: str) -> str:
    """otpauth:// URI for a QR code in an authenticator app (Google
    Authenticator, 1Password, etc.) — the standard TOTP enrollment UX."""
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="DITSALA Admin")


def verify_totp(*, secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def create_admin_mfa_enroll_token(admin_id: uuid.UUID, *, mfa_secret: str, jwt_secret: str) -> str:
    """
    Bridges `AdminAuthService.start_login`'s "not yet enrolled" branch to
    `enroll_mfa` — the freshly generated secret rides in this token rather
    than being written to `admin_users.mfa_secret` until the admin proves
    they can actually generate a valid code with it (otherwise a
    typo'd/never-scanned secret would silently brick the account's MFA).
    """
    payload = {
        "sub": str(admin_id),
        "type": ADMIN_MFA_ENROLL_TOKEN_TYPE,
        "mfa_secret": mfa_secret,
        "exp": datetime.now(UTC) + timedelta(minutes=ADMIN_MFA_TOKEN_TTL_MINUTES),
    }
    return jwt.encode(payload, jwt_secret, algorithm="HS256")


@dataclass(frozen=True)
class AdminMfaEnrollTokenPayload:
    admin_id: uuid.UUID
    mfa_secret: str


def decode_admin_mfa_enroll_token(
    token: str, *, jwt_secret: str
) -> AdminMfaEnrollTokenPayload:
    payload = jwt.decode(token, jwt_secret, algorithms=["HS256"])
    if payload.get("type") != ADMIN_MFA_ENROLL_TOKEN_TYPE:
        raise jwt.InvalidTokenError("Not an admin MFA enrollment token.")
    return AdminMfaEnrollTokenPayload(
        admin_id=uuid.UUID(payload["sub"]), mfa_secret=payload["mfa_secret"]
    )


def create_admin_login_token(admin_id: uuid.UUID, *, jwt_secret: str) -> str:
    """Issued once the admin's password checks out; exchanged for an
    access token by `POST /admin/auth/login/complete` with a valid TOTP
    code — mirrors the two-step shape of the user login flow (§17)."""
    payload = {
        "sub": str(admin_id),
        "type": ADMIN_LOGIN_TOKEN_TYPE,
        "exp": datetime.now(UTC) + timedelta(minutes=ADMIN_LOGIN_TOKEN_TTL_MINUTES),
    }
    return jwt.encode(payload, jwt_secret, algorithm="HS256")


def decode_admin_login_token(token: str, *, jwt_secret: str) -> uuid.UUID:
    payload = jwt.decode(token, jwt_secret, algorithms=["HS256"])
    if payload.get("type") != ADMIN_LOGIN_TOKEN_TYPE:
        raise jwt.InvalidTokenError("Not an admin login token.")
    return uuid.UUID(payload["sub"])


def create_admin_access_token(admin_id: uuid.UUID, *, jwt_secret: str, ttl_minutes: int) -> str:
    """
    Stateless, like the user access token — no refresh-token pair. Admin
    sessions are browser-based and shorter-lived by design (re-auth with
    password + TOTP on expiry is an acceptable UX cost for an internal
    tool in a way it wouldn't be for the mobile app's routine unlock).
    """
    payload = {
        "sub": str(admin_id),
        "type": ADMIN_ACCESS_TOKEN_TYPE,
        "exp": datetime.now(UTC) + timedelta(minutes=ttl_minutes),
    }
    return jwt.encode(payload, jwt_secret, algorithm="HS256")


def decode_admin_access_token(token: str, *, jwt_secret: str) -> uuid.UUID:
    payload = jwt.decode(token, jwt_secret, algorithms=["HS256"])
    if payload.get("type") != ADMIN_ACCESS_TOKEN_TYPE:
        raise jwt.InvalidTokenError("Not an admin access token.")
    return uuid.UUID(payload["sub"])


# --- §33: account recovery — next-of-kin "flag as suspicious" link ---

_RECOVERY_FLAG_TOKEN_TYPE = "recovery_flag"
RECOVERY_FLAG_TOKEN_TTL_DAYS = 7


def create_recovery_flag_token(recovery_request_id: uuid.UUID, *, jwt_secret: str) -> str:
    """
    Embedded in the link texted to next-of-kin (§33 step 3) — redeeming it
    is a public, unauthenticated GET (the next-of-kin has no DITSALA
    account), so the token itself is what proves "this is the person we
    texted," not a session. A 7-day TTL comfortably outlasts the recovery
    flow itself; a stale/reused link just fails closed.
    """
    payload = {
        "sub": str(recovery_request_id),
        "type": _RECOVERY_FLAG_TOKEN_TYPE,
        "exp": datetime.now(UTC) + timedelta(days=RECOVERY_FLAG_TOKEN_TTL_DAYS),
    }
    return jwt.encode(payload, jwt_secret, algorithm="HS256")


def decode_recovery_flag_token(token: str, *, jwt_secret: str) -> uuid.UUID:
    payload = jwt.decode(token, jwt_secret, algorithms=["HS256"])
    if payload.get("type") != _RECOVERY_FLAG_TOKEN_TYPE:
        raise jwt.InvalidTokenError("Not a recovery flag token.")
    return uuid.UUID(payload["sub"])
