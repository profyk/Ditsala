"""End-to-end API tests for /account/vip/* — real Postgres, real access tokens."""

import uuid
from collections.abc import AsyncIterator
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1.deps import SessionDep, get_vip_upgrade_service
from app.core.config import get_settings
from app.core.db import get_db_session
from app.core.security import create_access_token, hash_secret
from app.domain.billing.service import VIP_PRICING_CONFIG_KEY, VipUpgradeService
from app.main import app
from app.models.accounts import User
from app.models.admin import AdminUser
from app.repositories.admin import AdminRoleRepository, AdminUserRepository, SystemConfigRepository
from app.repositories.billing import VipSubscriptionRepository
from app.repositories.kyc import KycDocumentRepository, KycFaceVerificationRepository
from app.repositories.users import UserRepository
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
            system_config=SystemConfigRepository(db_session),
            payment_provider=StubPaymentProvider(),
            kyc_provider=StubKycProvider(),
        )

    app.dependency_overrides[get_db_session] = _override_db_session
    app.dependency_overrides[get_vip_upgrade_service] = _override_vip_upgrade_service
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
    role = await AdminRoleRepository(session).get_by_name("super_admin")
    assert role is not None
    admin = await AdminUserRepository(session).add(
        AdminUser(
            email=f"{uuid.uuid4()}@example.com",
            password_hash=hash_secret("irrelevant"),
            role_id=role.id,
        )
    )
    await SystemConfigRepository(session).upsert(
        key=VIP_PRICING_CONFIG_KEY,
        value={"amount_cents": 9900, "currency": "ZAR"},
        updated_by_admin_id=admin.id,
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
