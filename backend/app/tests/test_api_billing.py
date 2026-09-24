"""End-to-end API tests for /account/vip/* — real Postgres, real access tokens."""

import uuid
from collections.abc import AsyncIterator
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1.deps import SessionDep, get_conference_plan_upgrade_service, get_vip_upgrade_service
from app.core.config import get_settings
from app.core.db import get_db_session
from app.core.security import create_access_token, hash_secret
from app.domain.billing.conference_upgrade import ConferencePlanUpgradeService
from app.domain.billing.plans import PlanService
from app.domain.billing.service import (
    VIP_PLAN_CODE,
    VIP_PRICING_BILLING_INTERVAL,
    VipUpgradeService,
)
from app.main import app
from app.models.accounts import User
from app.models.admin import AdminUser
from app.repositories.admin import AdminRoleRepository, AdminUserRepository, AuditLogRepository
from app.repositories.billing import (
    ConferencePlanPurchaseRepository,
    EntitlementRepository,
    PlanPriceRepository,
    PlanRepository,
    VipSubscriptionRepository,
)
from app.repositories.kyc import KycDocumentRepository, KycFaceVerificationRepository
from app.repositories.users import UserRepository
from app.tests.test_conference_plan_upgrade_service import (
    StubPaymentProvider as ConferenceStubPayment,
)
from app.tests.test_onboarding_service import StubKycProvider
from app.tests.test_vip_upgrade_service import StubPaymentProvider


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

    async def _override_vip_upgrade_service(db_session: SessionDep) -> VipUpgradeService:
        return VipUpgradeService(
            users=UserRepository(db_session),
            vip_subscriptions=VipSubscriptionRepository(db_session),
            kyc_documents=KycDocumentRepository(db_session),
            kyc_face_verifications=KycFaceVerificationRepository(db_session),
            plans=PlanService(
                plans=PlanRepository(db_session),
                plan_prices=PlanPriceRepository(db_session),
                entitlements=EntitlementRepository(db_session),
                audit_log=AuditLogRepository(db_session),
                users=UserRepository(db_session),
            ),
            payment_provider=StubPaymentProvider(),
            kyc_provider=StubKycProvider(),
        )

    async def _override_conference_upgrade_service(
        db_session: SessionDep,
    ) -> ConferencePlanUpgradeService:
        return ConferencePlanUpgradeService(
            purchases=ConferencePlanPurchaseRepository(db_session),
            plans=PlanService(
                plans=PlanRepository(db_session),
                plan_prices=PlanPriceRepository(db_session),
                entitlements=EntitlementRepository(db_session),
                audit_log=AuditLogRepository(db_session),
                users=UserRepository(db_session),
            ),
            payment_provider=ConferenceStubPayment(),
        )

    app.dependency_overrides[get_db_session] = _override_db_session
    app.dependency_overrides[get_vip_upgrade_service] = _override_vip_upgrade_service
    app.dependency_overrides[get_conference_plan_upgrade_service] = (
        _override_conference_upgrade_service
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _make_active_user(session: AsyncSession) -> User:
    user = User(
        email=f"{uuid.uuid4()}@example.com",
        phone=f"+27{uuid.uuid4().int % 10**9}",
        display_name="API VIP Test User",
        date_of_birth=datetime(1990, 1, 1),
        national_id_hash=uuid.uuid4().hex,
        account_state="active",
    )
    session.add(user)
    await session.flush()
    return user


def _bearer_for(user: User) -> dict[str, str]:
    token = create_access_token(
        user_id=user.id,
        device_id=uuid.uuid4(),
        jwt_secret=get_settings().jwt_secret,
        ttl_minutes=15,
    )
    return {"Authorization": f"Bearer {token}"}


async def _set_pricing(session: AsyncSession) -> None:
    """Mirrors what an admin does for real via the /pricing page — the
    vip plan row itself is seeded by migration a1f5b8e3c2d7."""
    role = await AdminRoleRepository(session).get_by_name("super_admin")
    assert role is not None
    admin = await AdminUserRepository(session).add(
        AdminUser(
            email=f"{uuid.uuid4()}@example.com",
            password_hash=hash_secret("irrelevant"),
            role_id=role.id,
        )
    )
    plan_repo = PlanRepository(session)
    plan = await plan_repo.get_by_code(VIP_PLAN_CODE)
    assert plan is not None, "expected migration a1f5b8e3c2d7 to have seeded the 'vip' plan"
    plans = PlanService(
        plans=plan_repo,
        plan_prices=PlanPriceRepository(session),
        entitlements=EntitlementRepository(session),
        audit_log=AuditLogRepository(session),
        users=UserRepository(session),
    )
    await plans.set_price(
        admin_id=admin.id,
        plan_id=plan.id,
        currency="ZAR",
        amount_cents=9900,
        billing_interval=VIP_PRICING_BILLING_INTERVAL,
        reason="test setup",
    )


async def test_start_upgrade_without_pricing_returns_400(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await _make_active_user(session)
    r = await client.post("/api/v1/account/vip/upgrade/start", headers=_bearer_for(user))
    assert r.status_code == 400
    assert "pricing" in r.json()["detail"]


async def test_start_upgrade_returns_payment_url(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _set_pricing(session)
    user = await _make_active_user(session)

    r = await client.post("/api/v1/account/vip/upgrade/start", headers=_bearer_for(user))

    assert r.status_code == 200, r.text
    assert r.json()["payment_url"]
    assert r.json()["external_reference"]


async def test_kyc_document_start_requires_payment_first(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _set_pricing(session)
    user = await _make_active_user(session)

    r = await client.post(
        "/api/v1/account/vip/kyc/document/start",
        json={"document_type": "sa_id"},
        headers=_bearer_for(user),
    )
    assert r.status_code == 400


async def test_vip_routes_require_authentication(client: AsyncClient) -> None:
    r = await client.post("/api/v1/account/vip/upgrade/start")
    assert r.status_code == 401


async def test_conference_plan_upgrade_start_returns_payment_url(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await _make_active_user(session)

    r = await client.post(
        "/api/v1/account/conference-plan/upgrade/start",
        json={"plan_code": "conference_pro"},
        headers=_bearer_for(user),
    )

    assert r.status_code == 200, r.text
    assert r.json()["payment_url"]
    assert r.json()["external_reference"]
    assert r.json()["plan_code"] == "conference_pro"


async def test_conference_plan_upgrade_status_reflects_a_pending_purchase(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await _make_active_user(session)
    r = await client.post(
        "/api/v1/account/conference-plan/upgrade/start",
        json={"plan_code": "conference_pro"},
        headers=_bearer_for(user),
    )
    assert r.status_code == 200, r.text

    r = await client.get(
        "/api/v1/account/conference-plan/upgrade/status", headers=_bearer_for(user)
    )
    assert r.status_code == 200, r.text
    assert r.json()["plan_code"] == "conference_pro"
    assert r.json()["status"] == "pending_payment"


async def test_conference_plan_upgrade_rejects_unknown_plan_code(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await _make_active_user(session)

    r = await client.post(
        "/api/v1/account/conference-plan/upgrade/start",
        json={"plan_code": "not-a-real-plan"},
        headers=_bearer_for(user),
    )
    assert r.status_code == 400


async def test_conference_plan_routes_require_authentication(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/account/conference-plan/upgrade/start", json={"plan_code": "conference_pro"}
    )
    assert r.status_code == 401
