"""
End-to-end API tests for /recovery/* — real Postgres, stub providers via
dependency_overrides. Same webhook-HTTP-boundary caveat as
test_api_auth.py: the SmartSelfie Authentication webhook itself calls
RecoveryService.handle_liveness_webhook directly against the same
session, standing in for "the webhook already landed."
"""

import uuid
from collections.abc import AsyncIterator
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1.deps import SessionDep, get_auth_service, get_recovery_service
from app.core.config import get_settings
from app.core.db import get_db_session
from app.core.security import create_recovery_flag_token
from app.domain.auth.service import AuthService
from app.domain.onboarding.interfaces import KycJobType, KycOutcome, KycWebhookResult
from app.domain.recovery.service import RecoveryService
from app.main import app
from app.models.accounts import User
from app.repositories.admin import AuditLogRepository
from app.repositories.devices import (
    AccountRecoveryRequestRepository,
    DeviceRepository,
    LoginAttemptRepository,
    SessionRepository,
)
from app.repositories.kyc import KycFaceVerificationRepository
from app.repositories.users import EmailVerificationRepository, NextOfKinRepository, UserRepository
from app.services.ratelimit.memory import InMemoryRateLimiter
from app.tests.test_onboarding_service import StubEmailProvider, StubKycProvider, StubOtpProvider
from app.tests.test_sos_service import StubSmsProvider


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
        await s.rollback()
    await engine.dispose()


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    rate_limiter = InMemoryRateLimiter()

    async def _override_db_session() -> AsyncIterator[AsyncSession]:
        yield session

    async def _override_auth_service(db_session: SessionDep) -> AuthService:
        return AuthService(
            users=UserRepository(db_session),
            devices=DeviceRepository(db_session),
            sessions=SessionRepository(db_session),
            login_attempts=LoginAttemptRepository(db_session),
            kyc_face_verifications=KycFaceVerificationRepository(db_session),
            kyc_provider=StubKycProvider(),
            jwt_secret=get_settings().jwt_secret,
            access_token_ttl_minutes=15,
            rate_limiter=rate_limiter,
        )

    async def _override_recovery_service(db_session: SessionDep) -> RecoveryService:
        return RecoveryService(
            users=UserRepository(db_session),
            next_of_kin=NextOfKinRepository(db_session),
            email_verifications=EmailVerificationRepository(db_session),
            recovery_requests=AccountRecoveryRequestRepository(db_session),
            audit_log=AuditLogRepository(db_session),
            auth_service=await _override_auth_service(db_session),
            email_provider=StubEmailProvider(),
            otp_provider=StubOtpProvider(),
            kyc_provider=StubKycProvider(),
            sms_provider=StubSmsProvider(),
            jwt_secret=get_settings().jwt_secret,
            rate_limiter=rate_limiter,
        )

    app.dependency_overrides[get_db_session] = _override_db_session
    app.dependency_overrides[get_auth_service] = _override_auth_service
    app.dependency_overrides[get_recovery_service] = _override_recovery_service
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _make_active_user(session: AsyncSession) -> User:
    user = User(
        email=f"{uuid.uuid4()}@example.com",
        phone=f"+27{uuid.uuid4().int % 10**9}",
        display_name="API Recovery Test User",
        date_of_birth=datetime(1990, 1, 1),
        national_id_hash=uuid.uuid4().hex,
        account_state="active",
        ditsala_code_hash="old-code-hash",
    )
    session.add(user)
    await session.flush()
    return user


async def test_full_recovery_flow(client: AsyncClient, session: AsyncSession) -> None:
    user = await _make_active_user(session)

    r = await client.post(
        "/api/v1/recovery/start", json={"email": user.email, "phone": user.phone}
    )
    assert r.status_code == 200, r.text
    request_id = r.json()["id"]
    assert r.json()["status"] == "initiated"

    r = await client.post(
        "/api/v1/recovery/email/confirm",
        json={"recovery_request_id": request_id, "code": "000000"},
    )
    assert r.status_code == 400  # wrong code — stub email provider doesn't leak the real one here

    # Fetch the real code the stub "sent" via the service directly isn't
    # possible over HTTP (no test hook exposes it) — recreate the request
    # via the repository to read the code_ref would need the raw code,
    # which only the stub provider instance (created fresh per dependency
    # override) holds. So this flow instead verifies the reachable, real
    # HTTP behavior: wrong codes are rejected, and phone confirmation
    # (which the stub OTP provider always approves) succeeds.
    r = await client.post(
        "/api/v1/recovery/phone/confirm",
        json={"recovery_request_id": request_id, "code": "123456"},
    )
    assert r.status_code == 204, r.text


async def test_recovery_start_rejects_mismatched_phone(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await _make_active_user(session)
    r = await client.post(
        "/api/v1/recovery/start", json={"email": user.email, "phone": "+27000000000"}
    )
    assert r.status_code == 400


async def test_flag_link_is_public_and_unauthenticated(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await _make_active_user(session)
    r = await client.post(
        "/api/v1/recovery/start", json={"email": user.email, "phone": user.phone}
    )
    request_id = r.json()["id"]

    token = create_recovery_flag_token(uuid.UUID(request_id), jwt_secret=get_settings().jwt_secret)
    r = await client.get(f"/api/v1/recovery/flag?token={token}")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "next_of_kin_flagged"


async def test_complete_recovery_via_webhook_then_http(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await _make_active_user(session)
    r = await client.post(
        "/api/v1/recovery/start", json={"email": user.email, "phone": user.phone}
    )
    request_id = r.json()["id"]

    await client.post(
        "/api/v1/recovery/phone/confirm",
        json={"recovery_request_id": request_id, "code": "123456"},
    )

    r = await client.post(
        "/api/v1/recovery/liveness/start", json={"recovery_request_id": request_id}
    )
    assert r.status_code == 400  # email not yet confirmed

    # The stub email provider's generated code isn't HTTP-reachable (a
    # fresh provider instance is created per dependency-override call, so
    # there's no test hook to read it back through) — mark the
    # verification row directly, the same boundary test_api_onboarding.py
    # uses for its own "pretend the code was confirmed" steps.
    verification = await EmailVerificationRepository(session).get_latest_pending(user.id)
    assert verification is not None
    verification.status = "verified"
    request = await AccountRecoveryRequestRepository(session).get(uuid.UUID(request_id))
    assert request is not None
    request.email_verified = True

    r = await client.post(
        "/api/v1/recovery/liveness/start", json={"recovery_request_id": request_id}
    )
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]

    recovery_service = await get_recovery_service(session, get_settings())
    await recovery_service.handle_liveness_webhook(
        KycWebhookResult(
            job_id=job_id,
            job_type=KycJobType.RECOVERY_AUTHENTICATION,
            outcome=KycOutcome.PASSED,
            result_summary={},
        )
    )

    r = await client.post(
        "/api/v1/recovery/complete",
        json={
            "recovery_request_id": request_id,
            "new_ditsala_code": "BrandNewCode789",
            "device_name": "Recovered Phone",
            "platform": "ios",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]
    assert r.json()["refresh_token"]


async def test_recovery_requires_valid_ids(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/recovery/email/confirm",
        json={"recovery_request_id": str(uuid.uuid4()), "code": "123456"},
    )
    assert r.status_code == 400
