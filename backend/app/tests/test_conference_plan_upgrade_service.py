"""
Unit tests for ConferencePlanUpgradeService — real Postgres. The real
seeded conference_free/pro/premium/enterprise plans (migration
b4f7c1a9e6d2) exist, but their *prices* were deliberately removed
(migration b7d4e9f1a3c8, "do not hardcode plan pricings at all, admin
will") — every test that needs a price sets one explicitly via
PlanService.set_price, the same way a real admin would from /pricing.
Stub payment provider (ordinary test double for our own business
logic, same framing as test_vip_upgrade_service.py's).
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.security import hash_secret
from app.domain.billing.conference_upgrade import (
    ConferencePlanUpgradeError,
    ConferencePlanUpgradeService,
)
from app.domain.billing.interfaces import PaymentInitiation, PaymentProvider, PaymentWebhookResult
from app.domain.billing.plans import PlanService
from app.models.accounts import User
from app.models.admin import AdminUser
from app.repositories.admin import AdminRoleRepository, AdminUserRepository, AuditLogRepository
from app.repositories.billing import (
    ConferencePlanPurchaseRepository,
    EntitlementRepository,
    PlanPriceRepository,
    PlanRepository,
)
from app.repositories.users import UserRepository


class StubPaymentProvider(PaymentProvider):
    def __init__(self) -> None:
        self.initiated: list[dict[str, object]] = []

    async def initiate_payment(
        self, *, user_id: uuid.UUID, amount_cents: int, currency: str, description: str
    ) -> PaymentInitiation:
        reference = f"stub-conference-payment-{uuid.uuid4().hex[:8]}"
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
    service: ConferencePlanUpgradeService
    plans: PlanService
    plan_repo: PlanRepository
    users: UserRepository
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
    plan_repo = PlanRepository(session)
    plans = PlanService(
        plans=plan_repo,
        plan_prices=PlanPriceRepository(session),
        entitlements=EntitlementRepository(session),
        audit_log=AuditLogRepository(session),
        users=users,
    )
    payment_provider = StubPaymentProvider()
    service = ConferencePlanUpgradeService(
        purchases=ConferencePlanPurchaseRepository(session),
        plans=plans,
        payment_provider=payment_provider,
    )
    return Harness(
        service=service,
        plans=plans,
        plan_repo=plan_repo,
        users=users,
        payment_provider=payment_provider,
    )


@pytest.fixture
async def admin_id(session: AsyncSession) -> uuid.UUID:
    """A real `admin_users` row — `plan_prices`/audit_log writes have a
    genuine FK constraint to it, so a synthetic UUID won't do."""
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


async def _set_price(
    harness: Harness, admin_id: uuid.UUID, plan_code: str, *, amount_cents: int
) -> None:
    """Mirrors what an admin does for real via the /pricing page — no
    price is seeded for any conference plan any more (migration
    b7d4e9f1a3c8), including the free one, so every test that starts a
    real upgrade needs this first."""
    plan = await harness.plan_repo.get_by_code(plan_code)
    assert plan is not None, f"expected migration b4f7c1a9e6d2 to have seeded {plan_code!r}"
    await harness.plans.set_price(
        admin_id=admin_id,
        plan_id=plan.id,
        currency="ZAR",
        amount_cents=amount_cents,
        billing_interval="month",
        reason="test setup",
    )


async def _make_user(harness: Harness) -> User:
    return await harness.users.add(
        User(
            email=f"{uuid.uuid4()}@example.com",
            phone=f"+27{uuid.uuid4().int % 10**9}",
            display_name="Test User",
            date_of_birth=datetime(1990, 1, 1),
            national_id_hash=uuid.uuid4().hex,
            account_state="active",
        )
    )


async def test_start_upgrade_to_a_paid_plan_initiates_a_real_payment(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    user = await _make_user(harness)
    await _set_price(harness, admin_id, "conference_pro", amount_cents=14900)

    initiation = await harness.service.start_upgrade(user, plan_code="conference_pro")

    assert initiation is not None
    assert initiation.payment_url
    assert harness.payment_provider.initiated == [
        {"user_id": user.id, "amount_cents": 14900, "currency": "ZAR"}
    ]
    # Not applied yet — only the webhook, on real payment confirmation, does that.
    assert user.conference_plan_code == "conference_free"


async def test_start_upgrade_requires_pricing_configured(harness: Harness) -> None:
    """No price is seeded for any conference plan any more (migration
    b7d4e9f1a3c8) — an admin must set one from /pricing first, same
    "no default price by design" principle as VIP."""
    user = await _make_user(harness)
    with pytest.raises(ConferencePlanUpgradeError, match="no active price configured"):
        await harness.service.start_upgrade(user, plan_code="conference_pro")


async def test_start_upgrade_to_the_free_plan_applies_immediately_no_payment(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    user = await _make_user(harness)
    await harness.plans.apply_paid_conference_plan(user_id=user.id, plan_code="conference_pro")
    assert user.conference_plan_code == "conference_pro"
    # Even a free plan needs an explicit (zero) price set by an admin —
    # "no price row" means "not configured yet" for every plan, not an
    # implicit assumption that a missing price means free.
    await _set_price(harness, admin_id, "conference_free", amount_cents=0)

    initiation = await harness.service.start_upgrade(user, plan_code="conference_free")

    assert initiation is None
    assert harness.payment_provider.initiated == []
    assert user.conference_plan_code == "conference_free"


async def test_start_upgrade_rejects_unknown_plan_code(harness: Harness) -> None:
    user = await _make_user(harness)

    with pytest.raises(ConferencePlanUpgradeError, match="not a Conference Room plan"):
        await harness.service.start_upgrade(user, plan_code="not-a-real-plan")


async def test_start_upgrade_rejects_already_on_this_plan(harness: Harness) -> None:
    user = await _make_user(harness)

    with pytest.raises(ConferencePlanUpgradeError, match="already on this plan"):
        await harness.service.start_upgrade(user, plan_code="conference_free")


async def test_start_upgrade_rejects_a_second_upgrade_while_one_is_pending(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    user = await _make_user(harness)
    await _set_price(harness, admin_id, "conference_pro", amount_cents=14900)
    await _set_price(harness, admin_id, "conference_premium", amount_cents=39900)
    await harness.service.start_upgrade(user, plan_code="conference_pro")

    with pytest.raises(ConferencePlanUpgradeError, match="already in progress"):
        await harness.service.start_upgrade(user, plan_code="conference_premium")


async def test_payment_webhook_applies_the_plan_on_paid_and_marks_failed_otherwise(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    user = await _make_user(harness)
    await _set_price(harness, admin_id, "conference_pro", amount_cents=14900)
    initiation = await harness.service.start_upgrade(user, plan_code="conference_pro")
    assert initiation is not None

    purchase = await harness.service.handle_payment_webhook(
        PaymentWebhookResult(
            external_reference=initiation.external_reference, status="paid", raw={}
        )
    )
    assert purchase.status == "paid"
    assert purchase.paid_at is not None
    assert user.conference_plan_code == "conference_pro"


async def test_payment_webhook_rejects_unknown_reference(harness: Harness) -> None:
    with pytest.raises(ConferencePlanUpgradeError, match="Unknown payment reference"):
        await harness.service.handle_payment_webhook(
            PaymentWebhookResult(external_reference="never-existed", status="paid", raw={})
        )


async def test_failed_payment_does_not_change_the_plan(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    user = await _make_user(harness)
    await _set_price(harness, admin_id, "conference_pro", amount_cents=14900)
    initiation = await harness.service.start_upgrade(user, plan_code="conference_pro")
    assert initiation is not None

    purchase = await harness.service.handle_payment_webhook(
        PaymentWebhookResult(
            external_reference=initiation.external_reference, status="failed", raw={}
        )
    )
    assert purchase.status == "failed"
    assert user.conference_plan_code == "conference_free"
