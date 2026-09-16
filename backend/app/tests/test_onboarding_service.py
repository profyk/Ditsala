"""
Unit tests for the onboarding state machine (§14) using stub providers —
these are ordinary test doubles for *our own* business logic, not the
"never mock in a production code path" pattern the spec warns against
(that's about what ships, not what a test exercises). State still round-
trips through a real Postgres session, so the account_state transitions
are verified for real.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.domain.onboarding.interfaces import (
    EmailProvider,
    KycJobType,
    KycOutcome,
    KycProvider,
    KycSdkToken,
    KycWebhookResult,
    OtpProvider,
)
from app.domain.onboarding.service import OnboardingError, OnboardingService
from app.models.accounts import User
from app.models.admin import SystemConfig
from app.models.circle import Invitation
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


class StubEmailProvider(EmailProvider):
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_verification_code(self, *, to_email: str, code: str) -> None:
        self.sent.append((to_email, code))


class StubOtpProvider(OtpProvider):
    def __init__(self, *, approve: bool = True) -> None:
        self._approve = approve

    async def start_verification(self, *, phone_number: str) -> str:
        return "VEstubsid"

    async def check_verification(self, *, phone_number: str, code: str) -> bool:
        return self._approve


class StubKycProvider(KycProvider):
    async def create_sdk_token(self, *, user_id: uuid.UUID, job_type: KycJobType) -> KycSdkToken:
        # Unique per call (like the real adapter) — smile_id_job_id is a
        # unique column, and a user may retry a failed KYC job.
        job_id = f"job-{job_type.value}-{user_id.hex[:8]}-{uuid.uuid4().hex[:6]}"
        return KycSdkToken(token="stub-token", job_id=job_id)

    def verify_and_parse_webhook(
        self, *, payload: bytes, signature: str
    ) -> KycWebhookResult | None:
        raise NotImplementedError("not exercised in these tests")


@dataclass
class Harness:
    service: OnboardingService
    email: StubEmailProvider
    kyc_documents: KycDocumentRepository
    invitations: InvitationRepository
    system_config: SystemConfigRepository


@pytest.fixture
async def session():
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
        await s.rollback()
    await engine.dispose()


@pytest.fixture
def harness(session: AsyncSession) -> Harness:
    email = StubEmailProvider()
    kyc_documents = KycDocumentRepository(session)
    invitations = InvitationRepository(session)
    system_config = SystemConfigRepository(session)
    service = OnboardingService(
        users=UserRepository(session),
        email_verifications=EmailVerificationRepository(session),
        phone_verifications=PhoneVerificationRepository(session),
        next_of_kin=NextOfKinRepository(session),
        kyc_documents=kyc_documents,
        kyc_face_verifications=KycFaceVerificationRepository(session),
        invitations=invitations,
        system_config=system_config,
        email_provider=email,
        otp_provider=StubOtpProvider(),
        kyc_provider=StubKycProvider(),
        rate_limiter=InMemoryRateLimiter(),
    )
    return Harness(
        service=service,
        email=email,
        kyc_documents=kyc_documents,
        invitations=invitations,
        system_config=system_config,
    )


def _unique_signup_kwargs() -> dict[str, Any]:
    return {
        "email": f"{uuid.uuid4()}@test.local",
        "phone": f"+27{uuid.uuid4().int % 10**9}",
        "display_name": "Test User",
        "date_of_birth": datetime(1990, 1, 1),
        "national_id_hash": uuid.uuid4().hex,
    }


async def _reach_pending_next_of_kin(h: Harness, user: User) -> None:
    await h.service.confirm_email_verification(user, h.email.sent[0][1])
    await h.service.request_phone_verification(user)
    await h.service.confirm_phone_verification(user, "999999")  # stub approves any code

    document_token = await h.service.start_kyc_document_capture(user, document_type="sa_id")
    await h.service.handle_kyc_document_result(
        user,
        KycWebhookResult(
            job_id=document_token.job_id,
            job_type=KycJobType.DOCUMENT_VERIFICATION,
            outcome=KycOutcome.PASSED,
            result_summary={"result_code": "1012"},
        ),
    )

    liveness_token = await h.service.start_kyc_liveness(user)
    await h.service.handle_kyc_liveness_result(
        user,
        KycWebhookResult(
            job_id=liveness_token.job_id,
            job_type=KycJobType.SMARTSELFIE,
            outcome=KycOutcome.PASSED,
            result_summary={"confidence_value": 99.2},
        ),
    )


async def test_signup_sends_email_code_and_sets_pending_email(harness: Harness) -> None:
    user = await harness.service.start_signup(**_unique_signup_kwargs())
    assert user.account_state == "pending_email"
    assert len(harness.email.sent) == 1
    assert harness.email.sent[0][0] == user.email


async def test_confirm_email_verification_advances_to_pending_phone(harness: Harness) -> None:
    user = await harness.service.start_signup(**_unique_signup_kwargs())
    code = harness.email.sent[0][1]

    await harness.service.confirm_email_verification(user, code)

    assert user.account_state == "pending_phone"
    assert user.email_verified_at is not None


async def test_confirm_email_verification_rejects_wrong_code(harness: Harness) -> None:
    user = await harness.service.start_signup(**_unique_signup_kwargs())

    with pytest.raises(OnboardingError, match="Incorrect code"):
        await harness.service.confirm_email_verification(user, "000000")
    assert user.account_state == "pending_email"


async def test_full_flow_reaches_pending_code(harness: Harness) -> None:
    user = await harness.service.start_signup(**_unique_signup_kwargs())
    await _reach_pending_next_of_kin(harness, user)
    assert user.account_state == "pending_next_of_kin"

    await harness.service.add_next_of_kin(
        user, full_name="Jane Doe", relationship="Sister", phone="+27831234567", email=None
    )
    assert user.account_state == "pending_code"

    await harness.service.set_ditsala_code(user, "correct-horse-9")
    assert user.account_state == "pending_code"  # Phase 3 (device reg) completes it
    assert user.ditsala_code_hash is not None


async def test_kyc_document_failure_escalates_to_manual_review_after_max_attempts(
    harness: Harness,
) -> None:
    user = await harness.service.start_signup(**_unique_signup_kwargs())
    await harness.service.confirm_email_verification(user, harness.email.sent[0][1])
    await harness.service.request_phone_verification(user)
    await harness.service.confirm_phone_verification(user, "999999")

    for _ in range(3):
        token = await harness.service.start_kyc_document_capture(user, document_type="sa_id")
        await harness.service.handle_kyc_document_result(
            user,
            KycWebhookResult(
                job_id=token.job_id,
                job_type=KycJobType.DOCUMENT_VERIFICATION,
                outcome=KycOutcome.FAILED,
                result_summary={"result_code": "0810"},
            ),
        )

    assert user.account_state == "manual_review"


async def test_set_ditsala_code_rejects_weak_code(harness: Harness) -> None:
    user = await harness.service.start_signup(**_unique_signup_kwargs())
    await _reach_pending_next_of_kin(harness, user)
    await harness.service.add_next_of_kin(
        user, full_name="Jane Doe", relationship="Sister", phone="+27831234567", email=None
    )

    with pytest.raises(OnboardingError, match="DITSALA Code"):
        await harness.service.set_ditsala_code(user, "short1")


# --- §22/§28: invite-only mode ---


async def test_signup_open_by_default_without_invite_code(harness: Harness) -> None:
    user = await harness.service.start_signup(**_unique_signup_kwargs())
    assert user.account_state == "pending_email"


async def test_signup_requires_invite_code_when_invite_only_enabled(harness: Harness) -> None:
    await harness.system_config.add(
        SystemConfig(
            key="invite_only_mode", value={"enabled": True}, updated_at=datetime.now(UTC)
        )
    )

    with pytest.raises(OnboardingError, match="invitation code is required"):
        await harness.service.start_signup(**_unique_signup_kwargs())


async def test_signup_redeems_a_valid_invitation(harness: Harness) -> None:
    inviter = await harness.service.start_signup(**_unique_signup_kwargs())
    await harness.system_config.add(
        SystemConfig(
            key="invite_only_mode", value={"enabled": True}, updated_at=datetime.now(UTC)
        )
    )
    invitation = await harness.invitations.add(
        Invitation(
            inviter_user_id=inviter.id,
            invite_code="ABCD123456",
            channel="link",
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
    )

    user = await harness.service.start_signup(
        **_unique_signup_kwargs(), invite_code=invitation.invite_code
    )
    assert user.account_state == "pending_email"
    assert invitation.status == "redeemed"
    assert invitation.redeemed_by_user_id == user.id


async def test_signup_rejects_an_already_redeemed_invitation(harness: Harness) -> None:
    inviter = await harness.service.start_signup(**_unique_signup_kwargs())
    await harness.system_config.add(
        SystemConfig(
            key="invite_only_mode", value={"enabled": True}, updated_at=datetime.now(UTC)
        )
    )
    invitation = await harness.invitations.add(
        Invitation(
            inviter_user_id=inviter.id,
            invite_code="ABCD654321",
            channel="link",
            status="redeemed",
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
    )

    with pytest.raises(OnboardingError, match="Invalid or already-used"):
        await harness.service.start_signup(
            **_unique_signup_kwargs(), invite_code=invitation.invite_code
        )


async def test_signup_rejects_an_expired_invitation(harness: Harness) -> None:
    inviter = await harness.service.start_signup(**_unique_signup_kwargs())
    await harness.system_config.add(
        SystemConfig(
            key="invite_only_mode", value={"enabled": True}, updated_at=datetime.now(UTC)
        )
    )
    invitation = await harness.invitations.add(
        Invitation(
            inviter_user_id=inviter.id,
            invite_code="ABCD999999",
            channel="link",
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    )

    with pytest.raises(OnboardingError, match="expired"):
        await harness.service.start_signup(
            **_unique_signup_kwargs(), invite_code=invitation.invite_code
        )
    assert invitation.status == "expired"
