"""
Provider interfaces for onboarding (docs/DITSALA_MASTER_SPEC.md §3.4, §12).
Concrete adapters live in app/services/{email,otp,kyc}/ — a real adapter and
a Sandbox* adapter per interface, selected by env var only (see
app/services/factory.py). Domain/API code depends only on these Protocols,
never on a concrete adapter class.
"""

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class EmailProvider(Protocol):
    async def send_verification_code(self, *, to_email: str, code: str) -> None: ...


class OtpProvider(Protocol):
    async def start_verification(self, *, phone_number: str) -> str:
        """Returns the provider's verification reference (e.g. a Twilio Verification SID).
        We never generate or see the code itself — Twilio Verify owns that."""
        ...

    async def check_verification(self, *, phone_number: str, code: str) -> bool:
        """True if the submitted code is currently valid for this phone number."""
        ...


class KycJobType(StrEnum):
    DOCUMENT_VERIFICATION = "document_verification"
    SMARTSELFIE = "smartselfie"
    # Re-verification liveness for full server-side authentication — new
    # device, after logout, or recovery (docs/DITSALA_MASTER_SPEC.md §17).
    # Reuses the same SmartSelfie job mechanics and the kyc_face_verifications
    # table as onboarding's SMARTSELFIE step; see domain/auth/service.py.
    LOGIN_LIVENESS = "login_liveness"


class KycOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    MANUAL_REVIEW = "manual_review"


@dataclass(frozen=True)
class KycSdkToken:
    """Handed to the mobile Smile ID SDK, which drives capture UX natively
    and talks to Smile ID directly — see docs/DITSALA_MASTER_SPEC.md §12."""

    token: str
    job_id: str


@dataclass(frozen=True)
class KycWebhookResult:
    job_id: str
    job_type: KycJobType
    outcome: KycOutcome
    # Non-reversible fields only (scores/decision) — no imagery, ever. See §5, §34.2.
    result_summary: dict[str, Any]


class KycProvider(Protocol):
    async def create_sdk_token(self, *, user_id: uuid.UUID, job_type: KycJobType) -> KycSdkToken:
        """Requests a scoped, short-lived capture authorization for the mobile SDK."""
        ...

    def verify_and_parse_webhook(
        self, *, payload: bytes, signature: str
    ) -> KycWebhookResult | None:
        """None means the signature didn't verify — the caller must reject the request,
        never fall back to trusting an unsigned payload."""
        ...
