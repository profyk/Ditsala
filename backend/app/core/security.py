import hashlib
import hmac
import secrets
import string
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()

# DITSALA Code rules — docs/DITSALA_MASTER_SPEC.md §15. The breach-corpus
# check called for there isn't implemented (needs a real dataset/service —
# see docs/SECURITY_GAPS.md); this covers structural validation only.
MIN_CODE_LENGTH = 8


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


def generate_numeric_code(length: int = 6) -> str:
    """Cryptographically random — used for email verification codes (§10).
    Phone codes are Twilio Verify's own, never generated here."""
    return "".join(secrets.choice(string.digits) for _ in range(length))


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
