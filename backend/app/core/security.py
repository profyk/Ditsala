import hashlib
import hmac
import secrets
import string
import uuid
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
