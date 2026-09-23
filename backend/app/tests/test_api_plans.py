"""End-to-end API tests for the public /plans routes — real Postgres, real
access tokens. Backs the mobile "Conference Room" screen's plans/tools
comparison (see app/api/v1/routers/plans.py)."""

import uuid
from collections.abc import AsyncIterator
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.db import get_db_session
from app.core.security import create_access_token, hash_secret
from app.domain.billing.plans import PlanService
from app.main import app
from app.models.accounts import User
from app.models.admin import AdminUser
from app.repositories.admin import AdminRoleRepository, AdminUserRepository, AuditLogRepository
from app.repositories.billing import EntitlementRepository, PlanPriceRepository, PlanRepository
from app.repositories.users import UserRepository


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

    app.dependency_overrides[get_db_session] = _override_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _make_user(session: AsyncSession, *, account_tier: str = "normal") -> User:
    return await UserRepository(session).add(
        User(
            email=f"{uuid.uuid4()}@example.com",
            phone=f"+27{uuid.uuid4().int % 10**9}",
            display_name="API Plans Test User",
            date_of_birth=datetime(1990, 1, 1),
            national_id_hash=uuid.uuid4().hex,
            account_state="active",
            account_tier=account_tier,
        )
    )


def _bearer_for(user: User) -> dict[str, str]:
    token = create_access_token(
        user_id=user.id,
        device_id=uuid.uuid4(),
        jwt_secret=get_settings().jwt_secret,
        ttl_minutes=15,
    )
    return {"Authorization": f"Bearer {token}"}


async def _admin_id(session: AsyncSession) -> uuid.UUID:
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


async def test_list_plans_requires_authentication(client: AsyncClient) -> None:
    r = await client.get("/api/v1/plans")
    assert r.status_code == 401


async def test_list_plans_returns_only_active_plans_with_active_prices(
    client: AsyncClient, session: AsyncSession
) -> None:
    admin_id = await _admin_id(session)
    service = PlanService(
        plans=PlanRepository(session),
        plan_prices=PlanPriceRepository(session),
        entitlements=EntitlementRepository(session),
        audit_log=AuditLogRepository(session),
    )
    code = f"conf-{uuid.uuid4().hex[:8]}"
    plan = await service.create_plan(
        admin_id=admin_id, code=code, product="conference", name="Conference Room"
    )
    await service.set_price(
        admin_id=admin_id,
        plan_id=plan.id,
        currency="ZAR",
        amount_cents=19900,
        billing_interval="month",
        reason="initial price",
    )
    await service.set_entitlement(
        admin_id=admin_id, plan_id=plan.id, key="recording", value=True, reason="initial"
    )

    archived_code = f"old-{uuid.uuid4().hex[:8]}"
    archived_plan = await service.create_plan(
        admin_id=admin_id, code=archived_code, product="business", name="Old Business"
    )
    await service.set_plan_status(
        admin_id=admin_id, plan_id=archived_plan.id, status="archived", reason="retired"
    )

    user = await _make_user(session)
    r = await client.get("/api/v1/plans", headers=_bearer_for(user))

    assert r.status_code == 200, r.text
    codes = [p["code"] for p in r.json()]
    assert code in codes
    assert archived_code not in codes

    returned = next(p for p in r.json() if p["code"] == code)
    assert returned["prices"][0]["amount_cents"] == 19900
    assert returned["entitlements"][0] == {"key": "recording", "value": True}


async def test_my_plan_resolves_from_account_tier(
    client: AsyncClient, session: AsyncSession
) -> None:
    vip_user = await _make_user(session, account_tier="vip")
    r = await client.get("/api/v1/plans/me", headers=_bearer_for(vip_user))
    assert r.status_code == 200, r.text
    assert r.json()["plan_code"] == "vip"

    normal_user = await _make_user(session, account_tier="normal")
    r = await client.get("/api/v1/plans/me", headers=_bearer_for(normal_user))
    assert r.status_code == 200, r.text
    assert r.json()["plan_code"] == "free"
