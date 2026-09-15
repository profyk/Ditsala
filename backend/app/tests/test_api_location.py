"""
End-to-end API tests for /location/* — real Postgres. LocationService has
no external provider dependencies, so only get_db_session needs overriding.
"""

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
from app.models.circle import Contact
from app.models.devices import Device


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


async def _make_user_with_device(session: AsyncSession) -> tuple[User, Device, str]:
    user = User(
        email=f"{uuid.uuid4()}@example.com",
        phone=f"+27{uuid.uuid4().int % 10**9}",
        display_name="API Location Test User",
        date_of_birth=datetime(1990, 1, 1),
        national_id_hash=uuid.uuid4().hex,
        account_state="active",
    )
    session.add(user)
    await session.flush()
    device = Device(
        user_id=user.id, device_name="Test Device", platform="ios",
        first_seen_at=datetime.now(), last_seen_at=datetime.now(), is_trusted=True,
    )
    session.add(device)
    await session.flush()
    token = create_access_token(
        user.id, device.id, jwt_secret=get_settings().jwt_secret, ttl_minutes=15
    )
    return user, device, token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _trust(session: AsyncSession, owner_id: uuid.UUID, contact_id: uuid.UUID) -> None:
    session.add(Contact(owner_user_id=owner_id, contact_user_id=contact_id, tier="trusted"))
    await session.flush()


async def test_share_requires_trusted_tier(client: AsyncClient, session: AsyncSession) -> None:
    alice, _d1, alice_token = await _make_user_with_device(session)
    bob, _d2, _bob_token = await _make_user_with_device(session)

    r = await client.post(
        "/api/v1/location/shares",
        json={"recipient_user_id": str(bob.id), "duration_seconds": 3600},
        headers=_auth(alice_token),
    )
    assert r.status_code == 400
    assert "trusted" in r.text


async def test_full_location_share_flow(client: AsyncClient, session: AsyncSession) -> None:
    alice, _d1, alice_token = await _make_user_with_device(session)
    bob, _d2, bob_token = await _make_user_with_device(session)
    await _trust(session, alice.id, bob.id)

    r = await client.post(
        "/api/v1/location/shares",
        json={"recipient_user_id": str(bob.id), "duration_seconds": 3600},
        headers=_auth(alice_token),
    )
    assert r.status_code == 201, r.text
    share_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/location/shares/{share_id}/pings",
        json={"lat": -26.2, "lng": 28.0, "accuracy_m": 10.0},
        headers=_auth(alice_token),
    )
    assert r.status_code == 201, r.text

    r = await client.get(
        f"/api/v1/location/shares/{share_id}/pings", headers=_auth(bob_token)
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1

    r = await client.get(
        f"/api/v1/location/shares/{share_id}/access-log", headers=_auth(alice_token)
    )
    assert r.status_code == 200, r.text
    assert r.json()[0]["accessed_by_user_id"] == str(bob.id)

    r = await client.delete(f"/api/v1/location/shares/{share_id}", headers=_auth(alice_token))
    assert r.status_code == 204, r.text

    r = await client.get("/api/v1/location/shares/by-me", headers=_auth(alice_token))
    assert r.json() == []


async def test_location_requires_authentication(client: AsyncClient) -> None:
    r = await client.get("/api/v1/location/shares/by-me")
    assert r.status_code == 401
