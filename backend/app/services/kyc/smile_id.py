import base64
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime

import httpx

from app.core.config import Settings
from app.domain.onboarding.interfaces import (
    KycJobType,
    KycOutcome,
    KycProvider,
    KycSdkToken,
    KycWebhookResult,
)


class SmileIdProvider(KycProvider):
    """
    Real adapter — Smile ID's partner API (docs/DITSALA_MASTER_SPEC.md §12).

    The HMAC signing scheme below matches Smile ID's documented partner-
    authentication pattern (HMAC-SHA256 of timestamp + partner_id, keyed by
    the api_key, base64-encoded). Exact endpoint paths and response field
    names should be re-verified against Smile ID's current API reference
    before this goes live — it was written without a live Smile ID account
    to test against (see CLAUDE.md "Phase 2" notes), and Smile ID's API has
    product-specific variations (Document Verification, Enhanced KYC,
    SmartSelfie Authentication/Registration) that may differ from what's
    modeled here.
    """

    def __init__(
        self, *, partner_id: str, api_key: str, base_url: str, callback_url: str
    ) -> None:
        self._partner_id = partner_id
        self._api_key = api_key
        self._base_url = base_url
        self._callback_url = callback_url

    def _signature(self, timestamp: str) -> str:
        message = f"{timestamp}{self._partner_id}sid_request".encode()
        digest = hmac.new(self._api_key.encode(), message, hashlib.sha256).digest()
        return base64.b64encode(digest).decode()

    async def create_sdk_token(self, *, user_id: uuid.UUID, job_type: KycJobType) -> KycSdkToken:
        timestamp = datetime.now(UTC).isoformat()
        job_id = f"ditsala-{user_id}-{job_type.value}-{uuid.uuid4().hex[:8]}"
        payload = {
            "partner_id": self._partner_id,
            "timestamp": timestamp,
            "signature": self._signature(timestamp),
            "partner_params": {
                "user_id": str(user_id),
                "job_id": job_id,
                "job_type": job_type.value,
            },
            "callback_url": self._callback_url,
        }
        async with httpx.AsyncClient(base_url=self._base_url, timeout=15.0) as client:
            response = await client.post("/token", json=payload)
            response.raise_for_status()
            token: str = response.json()["token"]
        return KycSdkToken(token=token, job_id=job_id)

    def verify_and_parse_webhook(
        self, *, payload: bytes, signature: str
    ) -> KycWebhookResult | None:
        expected = hmac.new(self._api_key.encode(), payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return None

        data = json.loads(payload)
        result_code = data.get("ResultCode", "")
        outcome = (
            KycOutcome.PASSED
            if result_code.startswith("1")
            else KycOutcome.MANUAL_REVIEW
            if result_code.startswith("2")
            else KycOutcome.FAILED
        )
        return KycWebhookResult(
            job_id=data["PartnerParams"]["job_id"],
            job_type=KycJobType(data["PartnerParams"]["job_type"]),
            outcome=outcome,
            result_summary={
                "result_code": result_code,
                "result_text": data.get("ResultText"),
                "confidence_value": data.get("ConfidenceValue"),
            },
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "SmileIdProvider":
        return cls(
            partner_id=settings.smile_id_partner_id,
            api_key=settings.smile_id_api_key,
            base_url=settings.smile_id_api_base_url,
            callback_url=settings.smile_id_callback_url,
        )
