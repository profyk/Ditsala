"""
Unit tests for BypassKycProvider (docs/SECURITY_GAPS.md's "Dev-only KYC
bypass") — the sign/verify round-trip and token shape, which don't need
a live server. The full self-loopback webhook call (create_sdk_token's
background task actually reaching a running /webhooks/smile-id) was
verified manually against a live dev server, not via an automated test
here — see that section for why (this repo's real resource constraints
make spinning up a second live server per test run expensive).
"""

import uuid

import pytest

from app.domain.onboarding.interfaces import KycJobType, KycOutcome
from app.services.factory import get_kyc_provider
from app.services.kyc.bypass import BypassKycProvider


def _provider() -> BypassKycProvider:
    return BypassKycProvider(self_base_url="http://localhost:8000", bypass_secret="test-secret")


async def test_create_sdk_token_returns_a_well_formed_token() -> None:
    provider = _provider()
    token = await provider.create_sdk_token(
        user_id=uuid.uuid4(), job_type=KycJobType.DOCUMENT_VERIFICATION
    )
    assert token.token
    assert token.job_id.startswith("bypass-document_verification-")


def test_verify_and_parse_webhook_roundtrip() -> None:
    provider = _provider()
    payload = (
        b'{"job_id": "bypass-smartselfie-abc", "job_type": "smartselfie", '
        b'"outcome": "passed", "result_summary": {"bypass": true}}'
    )
    signature = provider._sign(payload)  # noqa: SLF001 — testing the private signer directly

    result = provider.verify_and_parse_webhook(payload=payload, signature=signature)

    assert result is not None
    assert result.job_id == "bypass-smartselfie-abc"
    assert result.job_type == KycJobType.SMARTSELFIE
    assert result.outcome == KycOutcome.PASSED


def test_verify_and_parse_webhook_rejects_bad_signature() -> None:
    provider = _provider()
    payload = (
        b'{"job_id": "x", "job_type": "smartselfie", "outcome": "passed", "result_summary": {}}'
    )

    result = provider.verify_and_parse_webhook(payload=payload, signature="not-the-real-signature")

    assert result is None


def test_factory_refuses_bypass_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings

    settings = Settings(kyc_provider="bypass", environment="production")
    with pytest.raises(ValueError, match="must never be used with ENVIRONMENT=production"):
        get_kyc_provider(settings)


def test_factory_allows_bypass_outside_production() -> None:
    from app.core.config import Settings

    settings = Settings(kyc_provider="bypass", environment="local")
    provider = get_kyc_provider(settings)
    assert isinstance(provider, BypassKycProvider)
