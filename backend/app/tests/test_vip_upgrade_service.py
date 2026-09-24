"""
Unit tests for VipUpgradeService (docs/adr/0012) — real Postgres, stub
payment/KYC providers (ordinary test doubles for *our own* business
logic, not the "never mock in a production code path" pattern — see
test_onboarding_service.py's identical framing for its own stubs).
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.security import hash_secret
from app.domain.billing.interfaces import PaymentInitiation, PaymentProvider, PaymentWebhookResult
from app.domain.billing.plans import PlanService
from app.domain.billing.service import (
    VIP_PLAN_CODE,
    VIP_PRICING_BILLING_INTERVAL,
    VipUpgradeError,
    VipUpgradeService,
)
from app.domain.onboarding.interfaces import KycJobType, KycOutcome, KycWebhookResult
from app.models.accounts import User
from app.models.admin import AdminUser
from app.repositories.admin import AdminRoleRepository, AdminUserRepository, AuditLogRepository
from app.repositories.billing import (
    EntitlementRepository,
    PlanPriceRepository,
    PlanRepository,
    VipSubscriptionRepository,
)
from app.repositories.kyc import KycDocumentRepository, KycFaceVerificationRepository
from app.repositories.users import UserRepository
from app.tests.test_onboarding_service import StubKycProvider


class StubPaymentProvider(PaymentProvider):
    def __init__(self) -> None:
        self.initiated: list[dict[str, object]] = []

    async def initiate_payment(
        self, *, user_id: uuid.UUID, amount_cents: int, currency: str, description: str
    ) -> PaymentInitiation:
        reference = f"stub-payment-{uuid.uuid4().hex[:8]}"
        self.initiated.append(
            {"user_id": user_id, "amount_cents": amount_cents, "currency": currency}
        )
        return PaymentInitiation(
            payment_url=f"https://pay.example/{reference}", external_reference=reference
        )

    def verify_and_parse_webhook(
        self, *, payload: bytes, signature: str
    ) -> PaymentWebhookResult | None:
        raise NotImplementedError("not exercised in these tests")


@dataclass
class Harness:
    service: VipUpgradeService
    users: UserRepository
    vip_subscriptions: VipSubscriptionRepository
    plans: PlanService
    plan_repo: PlanRepository
    payment_provider: StubPaymentProvider


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
    vip_subscriptions = VipSubscriptionRepository(session)
    plan_repo = PlanRepository(session)
    plans = PlanService(
        plans=plan_repo,
        plan_prices=PlanPriceRepository(session),
        entitlements=EntitlementRepository(session),
        audit_log=AuditLogRepository(session),
        users=users,
    )
    payment_provider = StubPaymentProvider()
    service = VipUpgradeService(
        users=users,
        vip_subscriptions=vip_subscriptions,
        kyc_documents=KycDocumentRepository(session),
        kyc_face_verifications=KycFaceVerificationRepository(session),
        plans=plans,
        payment_provider=payment_provider,
        kyc_provider=StubKycProvider(),
    )
    return Harness(
        service=service,
        users=users,
        vip_subscriptions=vip_subscriptions,
        plans=plans,
        plan_repo=plan_repo,
        payment_provider=payment_provider,
    )


async def _make_user(harness: Harness, **overrides: object) -> User:
    fields: dict[str, object] = {
        "email": f"{uuid.uuid4()}@example.com",
        "phone": f"+27{uuid.uuid4().int % 10**9}",
        "display_name": "VIP Test User",
        "date_of_birth": datetime(1990, 1, 1),
        "national_id_hash": uuid.uuid4().hex,
        "account_state": "active",
        **overrides,
    }
    return await harness.users.add(User(**fields))


@pytest.fixture
async def admin_id(session: AsyncSession) -> uuid.UUID:
    """A real `admin_users` row — `system_config.updated_by_admin_id` has
    a genuine FK constraint to it, so a synthetic UUID won't do."""
    role = await AdminRoleRepository(session).get_by_name("super_admin")
    assert role is not None, "expected seeded role 'super_admin' — did migrations run?"
    admin = await AdminUserRepository(session).add(
        AdminUser(
            email=f"{uuid.uuid4()}@example.com",
            password_hash=hash_secret("irrelevant-for-these-tests"),
            role_id=role.id,
        )
    )
    return admin.id


async def _set_pricing(
    harness: Harness,
    admin_id: uuid.UUID,
    *,
    amount_cents: int = 9900,
    currency: str = "ZAR",
) -> None:
    """Mirrors what an admin does for real via the /pricing page now —
    the vip plan row itself is seeded by migration a1f5b8e3c2d7 (real
    Postgres, so it's already there); only the price is test-specific."""
    plan = await harness.plan_repo.get_by_code(VIP_PLAN_CODE)
    assert plan is not None, "expected migration a1f5b8e3c2d7 to have seeded the 'vip' plan"
    await harness.plans.set_price(
        admin_id=admin_id,
        plan_id=plan.id,
        currency=currency,
        amount_cents=amount_cents,
        billing_interval=VIP_PRICING_BILLING_INTERVAL,
        reason="test setup",
    )


async def test_start_upgrade_requires_pricing_configured(harness: Harness) -> None:
    user = await _make_user(harness)
    with pytest.raises(VipUpgradeError, match="pricing has not been configured"):
        await harness.service.start_upgrade(user)


async def test_start_upgrade_initiates_payment_with_configured_price(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    user = await _make_user(harness)
    await _set_pricing(harness, admin_id, amount_cents=15000, currency="ZAR")

    initiation = await harness.service.start_upgrade(user)

    assert initiation.payment_url
    assert harness.payment_provider.initiated[0]["amount_cents"] == 15000
    assert harness.payment_provider.initiated[0]["currency"] == "ZAR"


async def test_start_upgrade_rejects_already_vip(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    user = await _make_user(harness, account_tier="vip")
    await _set_pricing(harness, admin_id)
    with pytest.raises(VipUpgradeError, match="already VIP"):
        await harness.service.start_upgrade(user)


async def test_start_upgrade_rejects_duplicate_in_progress(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    user = await _make_user(harness)
    await _set_pricing(harness, admin_id)
    await harness.service.start_upgrade(user)

    with pytest.raises(VipUpgradeError, match="already in progress"):
        await harness.service.start_upgrade(user)


async def test_kyc_requires_payment_first(harness: Harness) -> None:
    user = await _make_user(harness)
    with pytest.raises(VipUpgradeError, match="Complete VIP payment"):
        await harness.service.start_kyc_document(user, document_type="sa_id")


# --- ADR 0014: a phone-only account has no email/DOB/national ID yet ---


async def test_start_upgrade_requires_identity_fields_for_a_phone_only_account(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    user = await _make_user(
        harness, email=None, date_of_birth=None, national_id_hash=None
    )
    await _set_pricing(harness, admin_id)

    with pytest.raises(VipUpgradeError, match="Email, date of birth, and national ID"):
        await harness.service.start_upgrade(user)


async def test_start_upgrade_collects_identity_for_a_phone_only_account(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    user = await _make_user(
        harness, email=None, date_of_birth=None, national_id_hash=None
    )
    await _set_pricing(harness, admin_id)

    await harness.service.start_upgrade(
        user,
        email="new-vip@example.com",
        date_of_birth=datetime(1985, 5, 5),
        national_id_hash="hashed-id-value",
    )

    assert user.email == "new-vip@example.com"
    assert user.date_of_birth == datetime(1985, 5, 5)
    assert user.national_id_hash == "hashed-id-value"


async def test_start_upgrade_rejects_an_email_already_in_use(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    await _make_user(harness, email="taken@example.com")
    user = await _make_user(harness, email=None, date_of_birth=None, national_id_hash=None)
    await _set_pricing(harness, admin_id)

    with pytest.raises(VipUpgradeError, match="already exists"):
        await harness.service.start_upgrade(
            user,
            email="taken@example.com",
            date_of_birth=datetime(1985, 5, 5),
            national_id_hash="hashed-id-value",
        )


async def test_start_upgrade_does_not_re_collect_identity_for_an_existing_account(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    user = await _make_user(harness, email="already-set@example.com")
    await _set_pricing(harness, admin_id)

    # No identity kwargs supplied — should not raise, since the account
    # already has an email (e.g. the legacy email-first signup path).
    await harness.service.start_upgrade(user)
    assert user.email == "already-set@example.com"


async def test_full_upgrade_flow_flips_tier_to_vip(
    harness: Harness, session: AsyncSession, admin_id: uuid.UUID
) -> None:
    user = await _make_user(harness)
    await _set_pricing(harness, admin_id)

    initiation = await harness.service.start_upgrade(user)
    await harness.service.handle_payment_webhook(
        PaymentWebhookResult(
            external_reference=initiation.external_reference, status="paid", raw={}
        )
    )

    document_token = await harness.service.start_kyc_document(user, document_type="sa_id")
    await harness.service.handle_kyc_document_result(
        KycWebhookResult(
            job_id=document_token.job_id,
            job_type=KycJobType.DOCUMENT_VERIFICATION,
            outcome=KycOutcome.PASSED,
            result_summary={},
        )
    )

    liveness_token = await harness.service.start_kyc_liveness(user)
    await harness.service.handle_kyc_liveness_result(
        KycWebhookResult(
            job_id=liveness_token.job_id,
            job_type=KycJobType.SMARTSELFIE,
            outcome=KycOutcome.PASSED,
            result_summary={"confidence_value": 99.0},
        )
    )

    assert user.account_tier == "vip"
    subscription = await harness.vip_subscriptions.get_by_external_reference(
        initiation.external_reference
    )
    assert subscription is not None
    assert subscription.status == "active"


async def test_failed_payment_marks_subscription_failed(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    user = await _make_user(harness)
    await _set_pricing(harness, admin_id)
    initiation = await harness.service.start_upgrade(user)

    await harness.service.handle_payment_webhook(
        PaymentWebhookResult(
            external_reference=initiation.external_reference, status="failed", raw={}
        )
    )

    subscription = await harness.vip_subscriptions.get_by_external_reference(
        initiation.external_reference
    )
    assert subscription is not None
    assert subscription.status == "failed"
    assert user.account_tier == "normal"


async def test_liveness_before_document_passes_is_rejected(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    user = await _make_user(harness)
    await _set_pricing(harness, admin_id)
    initiation = await harness.service.start_upgrade(user)
    await harness.service.handle_payment_webhook(
        PaymentWebhookResult(
            external_reference=initiation.external_reference, status="paid", raw={}
        )
    )

    with pytest.raises(VipUpgradeError, match="Document verification must pass"):
        await harness.service.start_kyc_liveness(user)
