"""
Unit tests for PlanService — the config-driven plans/pricing/entitlements
layer (§27-29 of the business-model kickoff prompt). Real Postgres, same
pattern as test_vip_upgrade_service.py's `admin_id` fixture.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.security import hash_secret
from app.domain.billing.plans import PlanError, PlanService
from app.models.accounts import User
from app.models.admin import AdminUser
from app.repositories.admin import AdminRoleRepository, AdminUserRepository, AuditLogRepository
from app.repositories.billing import EntitlementRepository, PlanPriceRepository, PlanRepository
from app.repositories.users import UserRepository


@dataclass
class Harness:
    service: PlanService
    plans: PlanRepository
    users: UserRepository
    audit_log: AuditLogRepository


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
    plans = PlanRepository(session)
    audit_log = AuditLogRepository(session)
    service = PlanService(
        plans=plans,
        plan_prices=PlanPriceRepository(session),
        entitlements=EntitlementRepository(session),
        audit_log=audit_log,
    )
    return Harness(service=service, plans=plans, users=UserRepository(session), audit_log=audit_log)


@pytest.fixture
async def admin_id(session: AsyncSession) -> uuid.UUID:
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


async def _make_user(harness: Harness, *, account_tier: str = "normal") -> User:
    return await harness.users.add(
        User(
            email=f"{uuid.uuid4()}@example.com",
            phone=f"+27{uuid.uuid4().int % 10**9}",
            display_name="Plan Test User",
            date_of_birth=datetime(1990, 1, 1),
            national_id_hash=uuid.uuid4().hex,
            account_state="active",
            account_tier=account_tier,
        )
    )


# --- plans ---


async def test_create_plan(harness: Harness, admin_id: uuid.UUID) -> None:
    # A generic CRUD test — deliberately not code="vip", which migration
    # a1f5b8e3c2d7 now seeds for real (see test_get_entitlement_for_user_
    # resolves_through_plan below for the test that actually needs that
    # real row).
    plan = await harness.service.create_plan(
        admin_id=admin_id, code="vip_test", product="vip", name="Ditsala VIP Test"
    )
    assert plan.code == "vip_test"
    assert plan.status == "active"

    fetched = await harness.service.get_plan_by_code("vip_test")
    assert fetched is not None and fetched.id == plan.id


async def test_create_plan_rejects_duplicate_code(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    await harness.service.create_plan(
        admin_id=admin_id, code="vip_test", product="vip", name="Ditsala VIP Test"
    )
    with pytest.raises(PlanError, match="already exists"):
        await harness.service.create_plan(
            admin_id=admin_id, code="vip_test", product="vip", name="Ditsala VIP Test (dup)"
        )


async def test_set_plan_status_is_audit_logged(harness: Harness, admin_id: uuid.UUID) -> None:
    plan = await harness.service.create_plan(
        admin_id=admin_id,
        code="conference_starter",
        product="conference",
        name="Conference Starter",
    )
    updated = await harness.service.set_plan_status(
        admin_id=admin_id, plan_id=plan.id, status="archived", reason="retiring this tier"
    )
    assert updated.status == "archived"

    entries = await harness.audit_log.list_for_target("plan", plan.id)
    actions = [e.action for e in entries]
    assert "admin.plan.status_changed" in actions


# --- prices ---


async def test_set_price_creates_and_archives_previous(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    plan = await harness.service.create_plan(
        admin_id=admin_id, code="vip_test", product="vip", name="VIP Test"
    )

    first = await harness.service.set_price(
        admin_id=admin_id, plan_id=plan.id, currency="ZAR", amount_cents=9900,
        billing_interval="month", reason="initial launch price",
    )
    assert first.status == "active"

    active = await harness.service.get_active_price(
        plan_code="vip_test", currency="ZAR", billing_interval="month"
    )
    assert active is not None and active.id == first.id

    second = await harness.service.set_price(
        admin_id=admin_id, plan_id=plan.id, currency="ZAR", amount_cents=12900,
        billing_interval="month", reason="price increase",
    )

    prices = await harness.service.list_prices(plan.id)
    by_id = {p.id: p for p in prices}
    assert by_id[first.id].status == "archived"
    assert by_id[first.id].effective_until is not None
    assert by_id[second.id].status == "active"

    active_now = await harness.service.get_active_price(
        plan_code="vip_test", currency="ZAR", billing_interval="month"
    )
    assert active_now is not None and active_now.id == second.id
    assert active_now.amount_cents == 12900


async def test_get_active_price_returns_none_for_unpriced_plan(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    await harness.service.create_plan(
        admin_id=admin_id, code="business", product="business", name="Business"
    )
    price = await harness.service.get_active_price(
        plan_code="business", currency="ZAR", billing_interval="month"
    )
    assert price is None


async def test_set_price_requires_existing_plan(harness: Harness, admin_id: uuid.UUID) -> None:
    with pytest.raises(PlanError, match="No such plan"):
        await harness.service.set_price(
            admin_id=admin_id, plan_id=uuid.uuid4(), currency="ZAR", amount_cents=1000,
            billing_interval="month", reason="doesn't matter",
        )


# --- entitlements ---


async def test_set_and_list_entitlements(harness: Harness, admin_id: uuid.UUID) -> None:
    plan = await harness.service.create_plan(
        admin_id=admin_id, code="vip_test", product="vip", name="VIP Test"
    )

    await harness.service.set_entitlement(
        admin_id=admin_id, plan_id=plan.id, key="translation.text", value=True,
        reason="VIP gets unlimited text translation",
    )
    await harness.service.set_entitlement(
        admin_id=admin_id, plan_id=plan.id, key="interpretation.minutes_per_month", value=600,
        reason="10 hour default allowance",
    )

    entitlements = {e.key: e.value for e in await harness.service.list_entitlements(plan.id)}
    assert entitlements == {"translation.text": True, "interpretation.minutes_per_month": 600}


async def test_set_entitlement_overwrites_and_is_audit_logged(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    plan = await harness.service.create_plan(
        admin_id=admin_id, code="vip_test", product="vip", name="VIP Test"
    )
    await harness.service.set_entitlement(
        admin_id=admin_id, plan_id=plan.id, key="interpretation.minutes_per_month", value=600,
        reason="initial",
    )
    await harness.service.set_entitlement(
        admin_id=admin_id, plan_id=plan.id, key="interpretation.minutes_per_month", value=900,
        reason="increased allowance",
    )
    entitlements = await harness.service.list_entitlements(plan.id)
    assert len(entitlements) == 1
    assert entitlements[0].value == 900

    entries = await harness.audit_log.list_for_target("plan", plan.id)
    changed = [e for e in entries if e.action == "admin.plan.entitlement_changed"]
    assert len(changed) == 2
    # list_for_target orders newest-first, but two writes in the same test
    # can share a `created_at` tie — match by reason instead of trusting
    # position, so this doesn't flake on ordering.
    second_write = next(
        e for e in changed if (e.metadata_json or {}).get("reason") == "increased allowance"
    )
    assert second_write.metadata_json == {
        "key": "interpretation.minutes_per_month", "before": 600, "after": 900,
        "reason": "increased allowance",
    }


# --- resolution: what other domains call ---


async def test_resolve_plan_code_for_user(harness: Harness) -> None:
    normal_user = await _make_user(harness, account_tier="normal")
    vip_user = await _make_user(harness, account_tier="vip")
    assert harness.service.resolve_plan_code_for_user(normal_user) == "free"
    assert harness.service.resolve_plan_code_for_user(vip_user) == "vip"


async def test_get_entitlement_for_user_resolves_through_plan(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    # resolve_plan_code_for_user hardcodes "vip" for VIP-tier users
    # (DEFAULT_VIP_PLAN_CODE) — real Postgres, so the real row migration
    # a1f5b8e3c2d7 seeds is already there; not creating a duplicate.
    vip_plan = await harness.service.get_plan_by_code("vip")
    assert vip_plan is not None, "expected migration a1f5b8e3c2d7 to have seeded the 'vip' plan"
    await harness.service.set_entitlement(
        admin_id=admin_id, plan_id=vip_plan.id, key="translation.text", value=True,
        reason="VIP feature",
    )
    vip_user = await _make_user(harness, account_tier="vip")
    normal_user = await _make_user(harness, account_tier="normal")

    assert await harness.service.get_entitlement_for_user(vip_user, "translation.text") is True
    # normal-tier resolves to the "free" plan, which has no such entitlement row.
    assert (
        await harness.service.get_entitlement_for_user(
            normal_user, "translation.text", default=False
        )
        is False
    )


async def test_get_entitlement_for_user_falls_back_to_default_when_plan_missing(
    harness: Harness,
) -> None:
    """No "vip" plan row exists at all yet — resolution must not raise,
    just fall through to the caller's default (e.g. before an admin has
    ever configured plans in a fresh environment)."""
    vip_user = await _make_user(harness, account_tier="vip")
    value = await harness.service.get_entitlement_for_user(
        vip_user, "translation.text", default="unset"
    )
    assert value == "unset"
