"""
Unit tests for two-factor login, session issuance, and device management
(§14, §16-17) — stub KYC provider (see test_onboarding_service.py for why
that's fine here), real Postgres for state.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.security import decode_login_token, hash_secret
from app.domain.auth.service import MAX_CODE_ATTEMPTS, AuthError, AuthService
from app.domain.onboarding.interfaces import KycJobType, KycOutcome, KycWebhookResult
from app.models.accounts import User
from app.repositories.devices import DeviceRepository, LoginAttemptRepository, SessionRepository
from app.repositories.kyc import KycFaceVerificationRepository
from app.repositories.users import UserRepository
from app.tests.test_onboarding_service import StubKycProvider

JWT_SECRET = "test-secret-at-least-32-bytes-long-ok"


@dataclass
class Harness:
    service: AuthService
    users: UserRepository
    devices: DeviceRepository
    sessions: SessionRepository


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
        await s.rollback()
    await engine.dispose()


@pytest.fixture
def harness(session: AsyncSession) -> Harness:
    users = UserRepository(session)
    devices = DeviceRepository(session)
    sessions = SessionRepository(session)
    service = AuthService(
        users=users,
        devices=devices,
        sessions=sessions,
        login_attempts=LoginAttemptRepository(session),
        kyc_face_verifications=KycFaceVerificationRepository(session),
        kyc_provider=StubKycProvider(),
        jwt_secret=JWT_SECRET,
        access_token_ttl_minutes=15,
    )
    return Harness(service=service, users=users, devices=devices, sessions=sessions)


async def _make_user(users: UserRepository, *, state: str, code: str | None) -> User:
    user = User(
        email=f"{uuid.uuid4()}@example.com",
        phone=f"+27{uuid.uuid4().int % 10**9}",
        display_name="Auth Test User",
        date_of_birth=datetime(1990, 1, 1),
        national_id_hash=uuid.uuid4().hex,
        account_state=state,
    )
    if code is not None:
        user.ditsala_code_hash = hash_secret(code)
    return await users.add(user)


async def test_complete_onboarding_device_activates_account(harness: Harness) -> None:
    user = await _make_user(harness.users, state="pending_code", code="correct-horse-9")

    device, access_token, refresh_token = await harness.service.complete_onboarding_device(
        user, device_name="iPhone", platform="ios", push_token="tok-1"
    )

    assert user.account_state == "active"
    assert device.is_trusted is True
    assert access_token and refresh_token


async def test_complete_onboarding_device_rejects_wrong_state(harness: Harness) -> None:
    user = await _make_user(harness.users, state="pending_next_of_kin", code=None)

    with pytest.raises(AuthError):
        await harness.service.complete_onboarding_device(
            user, device_name="iPhone", platform="ios", push_token=None
        )


async def test_full_login_flow(harness: Harness) -> None:
    user = await _make_user(harness.users, state="active", code="correct-horse-9")

    login_token, sdk_token = await harness.service.start_login(
        identifier=user.email,
        ditsala_code="correct-horse-9",
        device_name="Pixel",
        platform="android",
        push_token=None,
        ip_hash="ip-hash",
    )

    await harness.service.record_login_liveness_result(
        KycWebhookResult(
            job_id=sdk_token.job_id,
            job_type=KycJobType.LOGIN_LIVENESS,
            outcome=KycOutcome.PASSED,
            result_summary={"confidence_value": 99.0},
        )
    )

    payload = decode_login_token(login_token, jwt_secret=JWT_SECRET)
    _user, device, access_token, refresh_token = await harness.service.complete_login(
        payload, ip_hash="ip-hash"
    )

    assert device.is_trusted is True
    assert access_token and refresh_token


async def test_login_rejects_wrong_code(harness: Harness) -> None:
    user = await _make_user(harness.users, state="active", code="correct-horse-9")

    with pytest.raises(AuthError, match="Invalid credentials"):
        await harness.service.start_login(
            identifier=user.email,
            ditsala_code="totally-wrong",
            device_name="Pixel",
            platform="android",
            push_token=None,
            ip_hash="ip-hash",
        )


async def test_login_completes_before_liveness_passes_is_rejected(harness: Harness) -> None:
    user = await _make_user(harness.users, state="active", code="correct-horse-9")
    login_token, _sdk_token = await harness.service.start_login(
        identifier=user.email,
        ditsala_code="correct-horse-9",
        device_name="Pixel",
        platform="android",
        push_token=None,
        ip_hash="ip-hash",
    )
    payload = decode_login_token(login_token, jwt_secret=JWT_SECRET)

    with pytest.raises(AuthError, match="Liveness check"):
        await harness.service.complete_login(payload, ip_hash="ip-hash")


async def test_lockout_after_max_failed_attempts(harness: Harness) -> None:
    user = await _make_user(harness.users, state="active", code="correct-horse-9")

    for _ in range(MAX_CODE_ATTEMPTS):
        with pytest.raises(AuthError):
            await harness.service.start_login(
                identifier=user.email,
                ditsala_code="wrong",
                device_name="Pixel",
                platform="android",
                push_token=None,
                ip_hash="ip-hash",
            )

    assert user.locked_until is not None
    assert user.locked_until > datetime.now(UTC)

    with pytest.raises(AuthError, match="temporarily locked"):
        await harness.service.start_login(
            identifier=user.email,
            ditsala_code="correct-horse-9",  # even the right code is rejected while locked
            device_name="Pixel",
            platform="android",
            push_token=None,
            ip_hash="ip-hash",
        )


async def test_refresh_rotates_token_and_detects_reuse(harness: Harness) -> None:
    user = await _make_user(harness.users, state="pending_code", code="correct-horse-9")
    _device, _access, refresh_token_1 = await harness.service.complete_onboarding_device(
        user, device_name="iPhone", platform="ios", push_token=None
    )

    access_2, refresh_token_2 = await harness.service.refresh_session(refresh_token_1)
    assert access_2 and refresh_token_2 != refresh_token_1

    # Replaying the now-rotated-away first refresh token is treated as
    # reuse — the whole family (including the second, currently-valid
    # token) gets revoked.
    with pytest.raises(AuthError, match="revoked"):
        await harness.service.refresh_session(refresh_token_1)

    with pytest.raises(AuthError):
        await harness.service.refresh_session(refresh_token_2)


async def test_revoke_device_revokes_its_sessions(harness: Harness) -> None:
    user = await _make_user(harness.users, state="pending_code", code="correct-horse-9")
    device, _access, refresh_token = await harness.service.complete_onboarding_device(
        user, device_name="iPhone", platform="ios", push_token=None
    )

    await harness.service.revoke_device(user, device.id)

    assert device.revoked_at is not None
    with pytest.raises(AuthError):
        await harness.service.refresh_session(refresh_token)


async def test_logout_all_revokes_every_session(harness: Harness) -> None:
    user = await _make_user(harness.users, state="pending_code", code="correct-horse-9")
    _device, _access, refresh_token = await harness.service.complete_onboarding_device(
        user, device_name="iPhone", platform="ios", push_token=None
    )

    await harness.service.revoke_all_sessions(user)

    with pytest.raises(AuthError):
        await harness.service.refresh_session(refresh_token)


async def test_logout_revokes_only_that_session(harness: Harness) -> None:
    user = await _make_user(harness.users, state="pending_code", code="correct-horse-9")
    _device1, _access1, refresh_token_1 = await harness.service.complete_onboarding_device(
        user, device_name="iPhone", platform="ios", push_token=None
    )

    # A genuine second session on a different device, via the login flow
    # (complete_onboarding_device only applies once, at pending_code).
    login_token, sdk_token = await harness.service.start_login(
        identifier=user.email,
        ditsala_code="correct-horse-9",
        device_name="iPad",
        platform="ios",
        push_token=None,
        ip_hash="ip-hash",
    )
    await harness.service.record_login_liveness_result(
        KycWebhookResult(
            job_id=sdk_token.job_id,
            job_type=KycJobType.LOGIN_LIVENESS,
            outcome=KycOutcome.PASSED,
            result_summary={},
        )
    )
    payload = decode_login_token(login_token, jwt_secret=JWT_SECRET)
    _user2, _device2, _access2, refresh_token_2 = await harness.service.complete_login(
        payload, ip_hash="ip-hash"
    )

    await harness.service.logout(refresh_token_1)

    with pytest.raises(AuthError):
        await harness.service.refresh_session(refresh_token_1)
    # The second device's session is untouched.
    access, new_refresh = await harness.service.refresh_session(refresh_token_2)
    assert access and new_refresh


async def test_list_devices_returns_registered_devices(harness: Harness) -> None:
    user = await _make_user(harness.users, state="pending_code", code="correct-horse-9")
    device, _access, _refresh = await harness.service.complete_onboarding_device(
        user, device_name="iPhone", platform="ios", push_token=None
    )

    devices = await harness.service.list_devices(user)
    assert [d.id for d in devices] == [device.id]
