"""
Unit tests for account recovery (§33) — real Postgres, stub external
providers (same boundary as onboarding/SOS tests: no real vendor
accounts in this environment).
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.security import create_recovery_flag_token, decode_recovery_flag_token
from app.domain.auth.service import AuthService
from app.domain.onboarding.interfaces import KycJobType, KycOutcome, KycWebhookResult
from app.domain.recovery.service import RecoveryError, RecoveryService
from app.models.accounts import NextOfKin, User
from app.models.devices import Device
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

TEST_JWT_SECRET = "test-recovery-jwt-secret-32-bytes-min!!"


@dataclass
class Harness:
    service: RecoveryService
    users: UserRepository
    next_of_kin: NextOfKinRepository
    recovery_requests: AccountRecoveryRequestRepository
    audit_log: AuditLogRepository
    email: StubEmailProvider
    sms: StubSmsProvider
    otp: StubOtpProvider


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
    next_of_kin = NextOfKinRepository(session)
    recovery_requests = AccountRecoveryRequestRepository(session)
    audit_log = AuditLogRepository(session)
    email = StubEmailProvider()
    sms = StubSmsProvider()
    otp = StubOtpProvider()
    auth_service = AuthService(
        users=users,
        devices=DeviceRepository(session),
        sessions=SessionRepository(session),
        login_attempts=LoginAttemptRepository(session),
        kyc_face_verifications=KycFaceVerificationRepository(session),
        kyc_provider=StubKycProvider(),
        jwt_secret=TEST_JWT_SECRET,
        access_token_ttl_minutes=15,
        rate_limiter=InMemoryRateLimiter(),
    )
    service = RecoveryService(
        users=users,
        next_of_kin=next_of_kin,
        email_verifications=EmailVerificationRepository(session),
        recovery_requests=recovery_requests,
        audit_log=audit_log,
        auth_service=auth_service,
        email_provider=email,
        otp_provider=otp,
        kyc_provider=StubKycProvider(),
        sms_provider=sms,
        jwt_secret=TEST_JWT_SECRET,
        rate_limiter=InMemoryRateLimiter(),
    )
    return Harness(
        service=service,
        users=users,
        next_of_kin=next_of_kin,
        recovery_requests=recovery_requests,
        audit_log=audit_log,
        email=email,
        sms=sms,
        otp=otp,
    )


async def _make_active_user(harness: Harness) -> User:
    return await harness.users.add(
        User(
            email=f"{uuid.uuid4()}@example.com",
            phone=f"+27{uuid.uuid4().int % 10**9}",
            display_name="Recovery Test User",
            date_of_birth=datetime(1990, 1, 1),
            national_id_hash=uuid.uuid4().hex,
            account_state="active",
            ditsala_code_hash="irrelevant-old-hash",
        )
    )


async def _verify_both(harness: Harness, request_id: uuid.UUID) -> None:
    code = harness.email.sent[-1][1]
    await harness.service.confirm_email(recovery_request_id=request_id, code=code)
    await harness.service.confirm_phone(recovery_request_id=request_id, code="000000")


async def test_start_recovery_requires_matching_email_and_phone(harness: Harness) -> None:
    user = await _make_active_user(harness)
    with pytest.raises(RecoveryError, match="No matching account"):
        await harness.service.start_recovery(email=user.email, phone="+27000000000")


async def test_start_recovery_rejects_non_active_accounts(harness: Harness) -> None:
    user = await _make_active_user(harness)
    user.account_state = "manual_review"
    with pytest.raises(RecoveryError, match="No matching account"):
        await harness.service.start_recovery(email=user.email, phone=user.phone)


async def test_start_recovery_sends_email_code(harness: Harness) -> None:
    user = await _make_active_user(harness)
    request = await harness.service.start_recovery(email=user.email, phone=user.phone)
    assert request.status == "initiated"
    assert len(harness.email.sent) == 1
    assert harness.email.sent[0][0] == user.email


async def test_confirm_email_and_phone_sets_flags(harness: Harness) -> None:
    user = await _make_active_user(harness)
    request = await harness.service.start_recovery(email=user.email, phone=user.phone)
    await _verify_both(harness, request.id)
    assert request.email_verified is True
    assert request.phone_verified is True


async def test_confirm_email_wrong_code_fails(harness: Harness) -> None:
    user = await _make_active_user(harness)
    request = await harness.service.start_recovery(email=user.email, phone=user.phone)
    with pytest.raises(RecoveryError, match="Incorrect code"):
        await harness.service.confirm_email(recovery_request_id=request.id, code="000000")


async def test_start_liveness_requires_both_verifications(harness: Harness) -> None:
    user = await _make_active_user(harness)
    request = await harness.service.start_recovery(email=user.email, phone=user.phone)
    with pytest.raises(RecoveryError, match="Confirm both email and phone"):
        await harness.service.start_liveness(request.id)

    await _verify_both(harness, request.id)
    token = await harness.service.start_liveness(request.id)
    assert token.job_id
    assert request.smile_id_job_id == token.job_id


async def test_liveness_webhook_pass_notifies_next_of_kin(harness: Harness) -> None:
    user = await _make_active_user(harness)
    await harness.next_of_kin.add(
        NextOfKin(
            user_id=user.id, full_name="Aunt Jane", relationship="Aunt", phone="+27831234567"
        )
    )
    request = await harness.service.start_recovery(email=user.email, phone=user.phone)
    await _verify_both(harness, request.id)
    token = await harness.service.start_liveness(request.id)

    await harness.service.handle_liveness_webhook(
        KycWebhookResult(
            job_id=token.job_id,
            job_type=KycJobType.RECOVERY_AUTHENTICATION,
            outcome=KycOutcome.PASSED,
            result_summary={"confidence_value": 99.5},
        )
    )
    assert request.status == "liveness_passed"
    assert len(harness.sms.sent) == 1
    assert harness.sms.sent[0]["to_phone"] == "+27831234567"


async def test_liveness_webhook_fail_sets_status(harness: Harness) -> None:
    user = await _make_active_user(harness)
    request = await harness.service.start_recovery(email=user.email, phone=user.phone)
    await _verify_both(harness, request.id)
    token = await harness.service.start_liveness(request.id)

    await harness.service.handle_liveness_webhook(
        KycWebhookResult(
            job_id=token.job_id,
            job_type=KycJobType.RECOVERY_AUTHENTICATION,
            outcome=KycOutcome.FAILED,
            result_summary={"confidence_value": 12.0},
        )
    )
    assert request.status == "liveness_failed"


async def test_flag_by_token_marks_request(harness: Harness) -> None:
    user = await _make_active_user(harness)
    request = await harness.service.start_recovery(email=user.email, phone=user.phone)
    token = create_recovery_flag_token(request.id, jwt_secret=TEST_JWT_SECRET)

    flagged = await harness.service.flag_by_token(token)
    assert flagged.status == "next_of_kin_flagged"


async def test_flag_by_token_rejects_invalid_token(harness: Harness) -> None:
    with pytest.raises(RecoveryError, match="Invalid or expired"):
        await harness.service.flag_by_token("not-a-real-token")


async def test_complete_requires_passed_liveness(harness: Harness) -> None:
    user = await _make_active_user(harness)
    request = await harness.service.start_recovery(email=user.email, phone=user.phone)
    with pytest.raises(RecoveryError, match="SmartSelfie Authentication must pass"):
        await harness.service.complete(
            recovery_request_id=request.id,
            new_ditsala_code="NewCode123",
            device_name="New Phone",
            platform="ios",
            push_token=None,
        )


async def test_complete_revokes_old_devices_and_issues_new_session(
    harness: Harness, session: AsyncSession
) -> None:
    user = await _make_active_user(harness)
    old_device = await DeviceRepository(session).add(
        Device(
            user_id=user.id,
            device_name="Old Phone",
            platform="android",
            first_seen_at=datetime.now(),
            last_seen_at=datetime.now(),
            is_trusted=True,
        )
    )
    request = await harness.service.start_recovery(email=user.email, phone=user.phone)
    await _verify_both(harness, request.id)
    token = await harness.service.start_liveness(request.id)
    await harness.service.handle_liveness_webhook(
        KycWebhookResult(
            job_id=token.job_id,
            job_type=KycJobType.RECOVERY_AUTHENTICATION,
            outcome=KycOutcome.PASSED,
            result_summary={},
        )
    )

    updated_user, device, access_token, refresh_token = await harness.service.complete(
        recovery_request_id=request.id,
        new_ditsala_code="BrandNewCode456",
        device_name="New Phone",
        platform="ios",
        push_token=None,
    )
    assert access_token and refresh_token
    assert device.device_name == "New Phone"
    assert old_device.revoked_at is not None
    assert updated_user.ditsala_code_hash != "irrelevant-old-hash"
    assert request.status == "completed"
    assert request.completed_at is not None
    assert request.new_device_id == device.id


async def test_decode_recovery_flag_token_roundtrip() -> None:
    request_id = uuid.uuid4()
    token = create_recovery_flag_token(request_id, jwt_secret=TEST_JWT_SECRET)
    assert decode_recovery_flag_token(token, jwt_secret=TEST_JWT_SECRET) == request_id
