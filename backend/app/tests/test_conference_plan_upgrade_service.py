"""
Unit tests for ConferencePlanUpgradeService — real Postgres (including
the real seeded conference_free/pro/premium/enterprise plans+prices from
migration b4f7c1a9e6d2), stub payment provider (ordinary test double for
our own business logic, same framing as test_vip_upgrade_service.py's).
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.domain.billing.conference_upgrade import (
    ConferencePlanUpgradeError,
    ConferencePlanUpgradeService,
)
from app.domain.billing.interfaces import PaymentInitiation, PaymentProvider, PaymentWebhookResult
from app.domain.billing.plans import PlanService
from app.models.accounts import User
from app.repositories.admin import AuditLogRepository
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
    plans = PlanService(
        plans=PlanRepository(session),
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
    return Harness(service=service, plans=plans, users=users, payment_provider=payment_provider)


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


async def test_start_upgrade_to_a_paid_plan_initiates_a_real_payment(harness: Harness) -> None:
    user = await _make_user(harness)

    initiation = await harness.service.start_upgrade(user, plan_code="conference_pro")

    assert initiation is not None
    assert initiation.payment_url
    assert harness.payment_provider.initiated == [
        {"user_id": user.id, "amount_cents": 14900, "currency": "ZAR"}
    ]
    # Not applied yet — only the webhook, on real payment confirmation, does that.
    assert user.conference_plan_code == "conference_free"


async def test_start_upgrade_to_the_free_plan_applies_immediately_no_payment(
    harness: Harness,
) -> None:
    user = await _make_user(harness)
    await harness.plans.apply_paid_conference_plan(user_id=user.id, plan_code="conference_pro")
    assert user.conference_plan_code == "conference_pro"

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
    harness: Harness,
) -> None:
    user = await _make_user(harness)
    await harness.service.start_upgrade(user, plan_code="conference_pro")

    with pytest.raises(ConferencePlanUpgradeError, match="already in progress"):
        await harness.service.start_upgrade(user, plan_code="conference_premium")


async def test_payment_webhook_applies_the_plan_on_paid_and_marks_failed_otherwise(
    harness: Harness,
) -> None:
    user = await _make_user(harness)
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


async def test_failed_payment_does_not_change_the_plan(harness: Harness) -> None:
    user = await _make_user(harness)
    initiation = await harness.service.start_upgrade(user, plan_code="conference_pro")
    assert initiation is not None

    purchase = await harness.service.handle_payment_webhook(
        PaymentWebhookResult(
            external_reference=initiation.external_reference, status="failed", raw={}
        )
    )
    assert purchase.status == "failed"
    assert user.conference_plan_code == "conference_free"
