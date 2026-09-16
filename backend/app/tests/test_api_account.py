"""End-to-end API tests for /account/* — real Postgres, real access tokens."""

import uuid
from collections.abc import AsyncIterator
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.db import get_db_session
from app.core.security import create_access_token
from app.main import app
from app.models.accounts import User
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


async def _make_active_user(session: AsyncSession) -> User:
    user = User(
        email=f"{uuid.uuid4()}@example.com",
        phone=f"+27{uuid.uuid4().int % 10**9}",
        display_name="API Account Test User",
        date_of_birth=datetime(1990, 1, 1),
        national_id_hash=uuid.uuid4().hex,
        account_state="active",
        ditsala_code_hash="irrelevant-hash",
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


async def test_deactivate_then_cancel(client: AsyncClient, session: AsyncSession) -> None:
    user = await _make_active_user(session)
    headers = _bearer_for(user)

    r = await client.post("/api/v1/account/deactivate", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["account_state"] == "deactivated"
    assert r.json()["hard_delete_after"] is not None

    r = await client.post("/api/v1/account/deactivate/cancel", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["account_state"] == "active"
    assert r.json()["hard_delete_after"] is None

    refreshed = await UserRepository(session).get(user.id)
    assert refreshed is not None
    assert refreshed.account_state == "active"


async def test_deactivate_twice_rejected(client: AsyncClient, session: AsyncSession) -> None:
    user = await _make_active_user(session)
    headers = _bearer_for(user)

    r = await client.post("/api/v1/account/deactivate", headers=headers)
    assert r.status_code == 200, r.text

    r = await client.post("/api/v1/account/deactivate", headers=headers)
    assert r.status_code == 400


async def test_cancel_without_deactivation_rejected(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await _make_active_user(session)
    headers = _bearer_for(user)

    r = await client.post("/api/v1/account/deactivate/cancel", headers=headers)
    assert r.status_code == 400


async def test_account_routes_require_auth(client: AsyncClient) -> None:
    r = await client.post("/api/v1/account/deactivate")
    assert r.status_code == 401


async def test_file_and_list_data_subject_requests(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await _make_active_user(session)
    headers = _bearer_for(user)

    r = await client.post(
        "/api/v1/account/data-requests",
        json={"request_type": "access", "details": "Please send me a copy of my data."},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "pending"
    assert r.json()["request_type"] == "access"

    r = await client.get("/api/v1/account/data-requests", headers=headers)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1


async def test_file_data_subject_request_rejects_unknown_type(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await _make_active_user(session)
    r = await client.post(
        "/api/v1/account/data-requests",
        json={"request_type": "bogus"},
        headers=_bearer_for(user),
    )
    assert r.status_code == 422
