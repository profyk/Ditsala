"""
End-to-end API tests for /auth/* — real Postgres, stub KYC provider via
dependency_overrides (see test_api_onboarding.py for the pattern and why).

The Smile ID webhook HTTP endpoint itself needs real signature-verification
setup and isn't exercised here (see docs/SECURITY_GAPS.md) — these tests
call AuthService.record_login_liveness_result directly against the same
session the API uses, standing in for "the webhook already landed",
exactly as test_api_onboarding.py does for the onboarding KYC steps.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1.deps import SessionDep, get_auth_service, get_onboarding_service
from app.core.config import get_settings
from app.core.db import get_db_session
from app.core.security import create_onboarding_token, hash_secret
from app.domain.auth.service import AuthService
from app.domain.onboarding.interfaces import KycJobType, KycOutcome, KycWebhookResult
from app.domain.onboarding.service import OnboardingService
from app.main import app
from app.models.accounts import User
from app.repositories.devices import DeviceRepository, LoginAttemptRepository, SessionRepository
from app.repositories.kyc import KycDocumentRepository, KycFaceVerificationRepository
from app.repositories.users import (
    EmailVerificationRepository,
    NextOfKinRepository,
    PhoneVerificationRepository,
    UserRepository,
)
from app.tests.test_onboarding_service import StubEmailProvider, StubKycProvider, StubOtpProvider

DITSALA_CODE = "correct-horse-9"


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
    async def _override_db_session() -> AsyncIterator[AsyncSession]:
        yield session

    async def _override_onboarding_service(db_session: SessionDep) -> OnboardingService:
        return OnboardingService(
            users=UserRepository(db_session),
            email_verifications=EmailVerificationRepository(db_session),
            phone_verifications=PhoneVerificationRepository(db_session),
            next_of_kin=NextOfKinRepository(db_session),
            kyc_documents=KycDocumentRepository(db_session),
            kyc_face_verifications=KycFaceVerificationRepository(db_session),
            email_provider=StubEmailProvider(),
            otp_provider=StubOtpProvider(),
            kyc_provider=StubKycProvider(),
        )

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
        )

    app.dependency_overrides[get_db_session] = _override_db_session
    app.dependency_overrides[get_onboarding_service] = _override_onboarding_service
    app.dependency_overrides[get_auth_service] = _override_auth_service
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _active_user_with_code(session: AsyncSession, *, code: str = DITSALA_CODE) -> User:
    user = User(
        email=f"{uuid.uuid4()}@example.com",
        phone=f"+27{uuid.uuid4().int % 10**9}",
        display_name="API Auth Test User",
        date_of_birth=datetime(1990, 1, 1),
        national_id_hash=uuid.uuid4().hex,
        account_state="active",
        ditsala_code_hash=hash_secret(code),
    )
    session.add(user)
    await session.flush()
    return user


async def _pending_code_user(session: AsyncSession, *, code: str = DITSALA_CODE) -> User:
    user = User(
        email=f"{uuid.uuid4()}@example.com",
        phone=f"+27{uuid.uuid4().int % 10**9}",
        display_name="API Auth Test User",
        date_of_birth=datetime(1990, 1, 1),
        national_id_hash=uuid.uuid4().hex,
        account_state="pending_code",
        ditsala_code_hash=hash_secret(code),
    )
    session.add(user)
    await session.flush()
    return user


def _device_payload(**overrides: Any) -> dict[str, Any]:
    return {
        "device_name": "iPhone 17",
        "platform": "ios",
        "push_token": None,
        **overrides,
    }


async def test_complete_onboarding_issues_a_session(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await _pending_code_user(session)
    onboarding_token = create_onboarding_token(user.id, jwt_secret=get_settings().jwt_secret)

    response = await client.post(
        "/api/v1/auth/complete-onboarding",
        json=_device_payload(),
        headers={"Authorization": f"Bearer {onboarding_token}"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_token"] and body["refresh_token"] and body["device_id"]
    assert user.account_state == "active"


async def test_full_login_flow_via_api(client: AsyncClient, session: AsyncSession) -> None:
    user = await _active_user_with_code(session)

    start = await client.post(
        "/api/v1/auth/login/start",
        json={
            "identifier": user.email,
            "ditsala_code": DITSALA_CODE,
            **_device_payload(),
        },
    )
    assert start.status_code == 200, start.text
    login_token = start.json()["login_token"]
    job_id = start.json()["job_id"]

    auth_service = AuthService(
        users=UserRepository(session),
        devices=DeviceRepository(session),
        sessions=SessionRepository(session),
        login_attempts=LoginAttemptRepository(session),
        kyc_face_verifications=KycFaceVerificationRepository(session),
        kyc_provider=StubKycProvider(),
        jwt_secret=get_settings().jwt_secret,
        access_token_ttl_minutes=15,
    )
    await auth_service.record_login_liveness_result(
        KycWebhookResult(
            job_id=job_id,
            job_type=KycJobType.LOGIN_LIVENESS,
            outcome=KycOutcome.PASSED,
            result_summary={},
        )
    )

    complete = await client.post(
        "/api/v1/auth/login/complete", json={"login_token": login_token}
    )
    assert complete.status_code == 200, complete.text
    body = complete.json()
    assert body["access_token"] and body["refresh_token"]


async def test_login_wrong_code_returns_401(client: AsyncClient, session: AsyncSession) -> None:
    user = await _active_user_with_code(session)

    response = await client.post(
        "/api/v1/auth/login/start",
        json={"identifier": user.email, "ditsala_code": "nope", **_device_payload()},
    )
    assert response.status_code == 401


async def test_refresh_and_device_management_via_api(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await _pending_code_user(session)
    onboarding_token = create_onboarding_token(user.id, jwt_secret=get_settings().jwt_secret)
    complete = await client.post(
        "/api/v1/auth/complete-onboarding",
        json=_device_payload(),
        headers={"Authorization": f"Bearer {onboarding_token}"},
    )
    access_token = complete.json()["access_token"]
    refresh_token = complete.json()["refresh_token"]
    device_id = complete.json()["device_id"]

    refreshed = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["refresh_token"] != refresh_token

    # The old, now-rotated-away refresh token is rejected.
    reuse = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert reuse.status_code == 401

    devices = await client.get(
        "/api/v1/auth/devices", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert devices.status_code == 200, devices.text
    assert len(devices.json()) == 1
    assert devices.json()[0]["id"] == device_id

    revoke = await client.delete(
        f"/api/v1/auth/devices/{device_id}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert revoke.status_code == 204


async def test_devices_endpoint_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/devices")
    assert response.status_code == 401
