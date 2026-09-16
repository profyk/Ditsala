"""
Dev/test-only KYC bypass — NOT a KycProvider in the "real vs. sandbox"
sense every other pair in this codebase follows (Working Rule 4). Real
KYC document/liveness capture needs a native Smile ID SDK wired into the
mobile app via a config plugin, which needs Xcode/Android Studio/EAS
build tooling this environment doesn't have (same root cause as ADR
0005's libsignal gap). This exists so the rest of the account lifecycle
— signup through login/logout — can be exercised end to end without a
real Smile ID account while that native integration doesn't exist, not
as a stand-in for identity verification anywhere a real user is
involved.

`services/factory.py` refuses to select this if `ENVIRONMENT=production`
— see that module. Every activation is logged loudly (structured log,
"kyc_bypass_used") specifically so it's never mistaken for the real
control passing. See docs/SECURITY_GAPS.md's "Dev-only KYC bypass"
section for the full disclosure.
"""

import asyncio
import hashlib
import hmac
import json
import uuid
from typing import Any

import httpx
import structlog

from app.core.config import Settings
from app.domain.onboarding.interfaces import (
    KycJobType,
    KycOutcome,
    KycProvider,
    KycSdkToken,
    KycWebhookResult,
)

_SIGNATURE_HEADER = "X-Smile-Signature"
# Long enough that the caller's own DB write (the KycDocument/
# KycFaceVerification row referencing this job_id) has certainly landed
# before this fires — see create_sdk_token's docstring for why that
# ordering matters. Short enough that a human tapping the mobile app's
# "check status" button never has to wait long.
_RESOLVE_DELAY_SECONDS = 1.0

_logger = structlog.get_logger()


class BypassKycProvider(KycProvider):
    def __init__(self, *, self_base_url: str, bypass_secret: str) -> None:
        self._self_base_url = self_base_url.rstrip("/")
        self._bypass_secret = bypass_secret

    @classmethod
    def from_settings(cls, settings: Settings) -> "BypassKycProvider":
        return cls(self_base_url=settings.self_base_url, bypass_secret=settings.jwt_secret)

    async def create_sdk_token(self, *, user_id: uuid.UUID, job_type: KycJobType) -> KycSdkToken:
        await _logger.awarning(
            "kyc_bypass_used", user_id=str(user_id), job_type=job_type.value
        )
        job_id = f"bypass-{job_type.value}-{uuid.uuid4().hex}"
        # Fire-and-forget, not awaited: the caller (OnboardingService/
        # AuthService/RecoveryService) writes the row referencing this
        # job_id *after* this method returns — the webhook handler needs
        # that row to exist to know which user the result belongs to.
        asyncio.create_task(self._resolve(job_id=job_id, job_type=job_type))
        return KycSdkToken(token="bypass-token", job_id=job_id)  # noqa: S106

    async def _resolve(self, *, job_id: str, job_type: KycJobType) -> None:
        await asyncio.sleep(_RESOLVE_DELAY_SECONDS)
        payload = json.dumps(
            {
                "job_id": job_id,
                "job_type": job_type.value,
                "outcome": KycOutcome.PASSED.value,
                "result_summary": {"bypass": True},
            }
        ).encode()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"{self._self_base_url}/api/v1/webhooks/smile-id",
                    content=payload,
                    headers={
                        _SIGNATURE_HEADER: self._sign(payload),
                        "Content-Type": "application/json",
                    },
                )
        except httpx.HTTPError:
            await _logger.aerror("kyc_bypass_self_webhook_failed", job_id=job_id)

    def _sign(self, payload: bytes) -> str:
        return hmac.new(self._bypass_secret.encode(), payload, hashlib.sha256).hexdigest()

    def verify_and_parse_webhook(
        self, *, payload: bytes, signature: str
    ) -> KycWebhookResult | None:
        if not hmac.compare_digest(self._sign(payload), signature):
            return None
        data: dict[str, Any] = json.loads(payload)
        return KycWebhookResult(
            job_id=data["job_id"],
            job_type=KycJobType(data["job_type"]),
            outcome=KycOutcome(data["outcome"]),
            result_summary=data["result_summary"],
        )
