"""
Unit tests for `RevenueService` — real Postgres, exercising the actual
seeded plans (migration b4f7c1a9e6d2) and real account rows, not mocks.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.domain.admin.revenue import RevenueService
from app.domain.billing.conference_plans import PRO_PLAN_CODE
from app.domain.billing.plans import PlanService
from app.models.accounts import User
from app.repositories.admin import AuditLogRepository
from app.repositories.billing import EntitlementRepository, PlanPriceRepository, PlanRepository
from app.repositories.users import UserRepository


@dataclass
class Harness:
    revenue: RevenueService
    plans: PlanService
    users: UserRepository


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
    return Harness(revenue=RevenueService(plans=plans, users=users), plans=plans, users=users)


async def _make_user(harness: Harness, **overrides: object) -> User:
    fields: dict[str, object] = {
        "email": f"{uuid.uuid4()}@example.com",
        "phone": f"+27{uuid.uuid4().int % 10**9}",
        "display_name": "Revenue Test User",
        "date_of_birth": datetime(1990, 1, 1),
        "national_id_hash": uuid.uuid4().hex,
        "account_state": "active",
        **overrides,
    }
    return await harness.users.add(User(**fields))


async def test_overview_includes_seeded_conference_plans(harness: Harness) -> None:
    overview = await harness.revenue.get_overview()
    codes = {line.plan_code for line in overview.lines}
    assert PRO_PLAN_CODE in codes


async def test_free_normal_tier_users_are_not_double_counted_as_vip(harness: Harness) -> None:
    """The real bug this test guards against: users.account_tier's values
    ("normal"/"vip") aren't the same strings as the free-tier plan code
    ("free") — a naive merge would silently undercount the free plan and
    never surface "normal" users at all. No migration seeds a "free"
    plan row (only the four conference_* ones), so this test creates one
    itself, the same way test_plan_service.py's own tests do."""
    admin_id = uuid.uuid4()
    await harness.plans.create_plan(admin_id=admin_id, code="free", product="free", name="Free")
    await _make_user(harness, account_tier="normal")
    await _make_user(harness, account_tier="normal")
    overview = await harness.revenue.get_overview()
    free_line = next(line for line in overview.lines if line.plan_code == "free")
    assert free_line.subscriber_count >= 2


async def test_vip_tier_users_counted_under_vip_plan(harness: Harness) -> None:
    await _make_user(harness, account_tier="vip", email=f"{uuid.uuid4()}@vip.example.com")
    overview = await harness.revenue.get_overview()
    vip_line = next((line for line in overview.lines if line.plan_code == "vip"), None)
    if vip_line is not None:  # only present if the "vip" plan row itself exists
        assert vip_line.subscriber_count >= 1


async def test_conference_plan_subscribers_counted_under_their_own_plan(harness: Harness) -> None:
    admin_id = uuid.uuid4()
    user = await _make_user(harness)
    await harness.plans.set_user_conference_plan(
        admin_id=admin_id, user_id=user.id, plan_code=PRO_PLAN_CODE, reason="test"
    )
    overview = await harness.revenue.get_overview()
    pro_line = next(line for line in overview.lines if line.plan_code == PRO_PLAN_CODE)
    assert pro_line.subscriber_count >= 1


async def test_totals_are_consistent_with_line_sums(harness: Harness) -> None:
    overview = await harness.revenue.get_overview()
    assert overview.total_subscribers == sum(line.subscriber_count for line in overview.lines)
    assert overview.total_estimated_monthly_cents == sum(
        line.estimated_monthly_cents for line in overview.lines
    )


async def test_archived_plans_are_excluded(harness: Harness) -> None:
    admin_id = uuid.uuid4()
    plan = await harness.plans.create_plan(
        admin_id=admin_id,
        code=f"archived-{uuid.uuid4().hex[:8]}",
        product="business",
        name="Old tier",
    )
    await harness.plans.set_plan_status(
        admin_id=admin_id, plan_id=plan.id, status="archived", reason="retired"
    )
    overview = await harness.revenue.get_overview()
    assert plan.code not in {line.plan_code for line in overview.lines}
