"""
End-to-end API tests for the onboarding routes — real Postgres underneath,
stub providers swapped in via FastAPI's dependency_overrides so the test
suite doesn't need live Twilio/Smile ID/Resend accounts (see
app/tests/test_onboarding_service.py for why stubbing our own test
doubles here is fine, and app/tests/test_sandbox_email_provider.py for
the one path that *is* exercised against real infra, Mailpit).

Uses httpx.AsyncClient(transport=ASGITransport(...)) rather than
starlette.testclient.TestClient deliberately: TestClient runs the ASGI app
in a separate thread with its own event loop, and on Windows mixing an
asyncpg connection across that loop and the test's own pytest-asyncio loop
corrupts the connection at teardown ("Event loop is closed"). Running
everything in-process on one loop avoids that entirely.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1.deps import SessionDep, get_onboarding_service
from app.core.config import get_settings
from app.core.db import get_db_session
from app.domain.onboarding.service import OnboardingService
from app.main import app
from app.repositories.admin import SystemConfigRepository
from app.repositories.circle import InvitationRepository
from app.repositories.kyc import KycDocumentRepository, KycFaceVerificationRepository
from app.repositories.users import (
    EmailVerificationRepository,
    NextOfKinRepository,
    PhoneVerificationRepository,
    UserRepository,
)
from app.services.ratelimit.memory import InMemoryRateLimiter
from app.tests.test_onboarding_service import StubEmailProvider, StubKycProvider, StubOtpProvider


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
        await s.rollback()
    await engine.dispose()


@pytest.fixture
def email_provider() -> StubEmailProvider:
    return StubEmailProvider()


@pytest.fixture
async def client(
    session: AsyncSession, email_provider: StubEmailProvider
) -> AsyncIterator[AsyncClient]:
    # Both overrides must share the same session: get_current_onboarding_user
    # (via SessionDep) looks the user up in one transaction, and
    # get_onboarding_service must see that same uncommitted row across the
    # several sequential requests one test makes — hence resolving the
    # service's session via Depends(get_db_session) rather than closing
    # over the fixture variable, so FastAPI's override machinery applies
    # to it too.
    rate_limiter = InMemoryRateLimiter()

    async def _override_db_session() -> AsyncIterator[AsyncSession]:
        yield session

    async def _override_service(db_session: SessionDep) -> OnboardingService:
        return OnboardingService(
            users=UserRepository(db_session),
            email_verifications=EmailVerificationRepository(db_session),
            phone_verifications=PhoneVerificationRepository(db_session),
            next_of_kin=NextOfKinRepository(db_session),
            kyc_documents=KycDocumentRepository(db_session),
            kyc_face_verifications=KycFaceVerificationRepository(db_session),
            invitations=InvitationRepository(db_session),
            system_config=SystemConfigRepository(db_session),
            email_provider=email_provider,
            otp_provider=StubOtpProvider(),
            kyc_provider=StubKycProvider(),
            rate_limiter=rate_limiter,
        )

    app.dependency_overrides[get_db_session] = _override_db_session
    app.dependency_overrides[get_onboarding_service] = _override_service
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


def _signup_payload() -> dict[str, Any]:
    return {
        # RFC 2606 reserves example.com for exactly this — email-validator
        # (via Pydantic's EmailStr) rejects .local as a special-use TLD.
        "email": f"{uuid.uuid4()}@example.com",
        "phone": f"+27{uuid.uuid4().int % 10**9}",
        "display_name": "API Test User",
        "date_of_birth": "1990-01-01",
        "national_id": uuid.uuid4().hex,
    }


async def test_signup_returns_onboarding_token(client: AsyncClient) -> None:
    response = await client.post("/api/v1/onboarding/signup", json=_signup_payload())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["account_state"] == "pending_email"
    assert body["onboarding_token"]


async def test_signup_rejects_duplicate_email(client: AsyncClient) -> None:
    payload = _signup_payload()
    first = await client.post("/api/v1/onboarding/signup", json=payload)
    assert first.status_code == 201

    second = await client.post(
        "/api/v1/onboarding/signup", json={**_signup_payload(), "email": payload["email"]}
    )
    assert second.status_code == 400


async def test_status_reflects_current_account_state(client: AsyncClient) -> None:
    signup = await client.post("/api/v1/onboarding/signup", json=_signup_payload())
    token = signup.json()["onboarding_token"]

    response = await client.get(
        "/api/v1/onboarding/status", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["account_state"] == "pending_email"


async def test_missing_token_is_rejected(client: AsyncClient) -> None:
    response = await client.post("/api/v1/onboarding/email/confirm", json={"code": "123456"})
    assert response.status_code == 401


async def test_email_confirm_wrong_code_returns_400(client: AsyncClient) -> None:
    signup = await client.post("/api/v1/onboarding/signup", json=_signup_payload())
    token = signup.json()["onboarding_token"]

    response = await client.post(
        "/api/v1/onboarding/email/confirm",
        json={"code": "000000"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400


async def test_full_onboarding_flow_via_api(
    client: AsyncClient, session: AsyncSession, email_provider: StubEmailProvider
) -> None:
    payload = _signup_payload()
    signup = await client.post("/api/v1/onboarding/signup", json=payload)
    assert signup.status_code == 201
    token = signup.json()["onboarding_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # ADR 0012: only a `vip` account passes through the KYC steps this
    # test exercises — real signups are always `normal` (VIP is a
    # post-active upgrade), so this opts in directly via the DB, the same
    # way test_onboarding_service.py's equivalent helper does.
    user = await UserRepository(session).get_by_email(payload["email"])
    assert user is not None
    user.account_tier = "vip"

    code = email_provider.sent[0][1]
    r = await client.post(
        "/api/v1/onboarding/email/confirm", json={"code": code}, headers=headers
    )
    assert r.status_code == 200
    assert r.json()["account_state"] == "pending_phone"

    r = await client.post("/api/v1/onboarding/phone/request", headers=headers)
    assert r.status_code == 200
    r = await client.post(
        "/api/v1/onboarding/phone/confirm", json={"code": "999999"}, headers=headers
    )
    assert r.status_code == 200
    assert r.json()["account_state"] == "pending_kyc_document"

    r = await client.post(
        "/api/v1/onboarding/kyc/document/start",
        json={"document_type": "sa_id"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["job_id"]

    r = await client.post(
        "/api/v1/onboarding/next-of-kin",
        json={
            "full_name": "Jane Doe",
            "relationship": "Sister",
            "phone": "+27831234567",
            "email": None,
        },
        headers=headers,
    )
    # Still in pending_kyc_document/pending_kyc_liveness in this flow since
    # the webhook (KYC result) never landed — confirms the API rejects an
    # out-of-order step rather than silently accepting it.
    assert r.status_code == 400


async def test_normal_tier_signup_skips_kyc_via_api(
    client: AsyncClient, email_provider: StubEmailProvider
) -> None:
    """ADR 0012 — the real, unmodified signup flow (no DB-side tier
    override) never enters a KYC state at all."""
    signup = await client.post("/api/v1/onboarding/signup", json=_signup_payload())
    token = signup.json()["onboarding_token"]
    headers = {"Authorization": f"Bearer {token}"}

    code = email_provider.sent[0][1]
    await client.post(
        "/api/v1/onboarding/email/confirm", json={"code": code}, headers=headers
    )
    await client.post("/api/v1/onboarding/phone/request", headers=headers)
    r = await client.post(
        "/api/v1/onboarding/phone/confirm", json={"code": "999999"}, headers=headers
    )

    assert r.status_code == 200, r.text
    assert r.json()["account_state"] == "pending_next_of_kin"
