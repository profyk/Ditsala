"""
End-to-end API tests for /sos/* — real Postgres, stub push/SMS providers
(same boundary as the domain-level SOS tests: a safety feature's test
suite shouldn't make real network calls, the adapters are the tested unit
for that).
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1.deps import SessionDep, get_sos_service
from app.core.config import get_settings
from app.core.db import get_db_session
from app.core.security import create_access_token
from app.domain.sos.service import SOS_TRIGGER_LIMIT, SosService
from app.main import app
from app.models.accounts import User
from app.models.circle import Contact
from app.models.devices import Device
from app.repositories.admin import SystemConfigRepository
from app.repositories.circle import ContactRepository
from app.repositories.devices import DeviceRepository
from app.repositories.sos import SosEventRepository, SosNotificationRepository
from app.repositories.users import NextOfKinRepository, UserRepository
from app.services.ratelimit.memory import InMemoryRateLimiter
from app.tests.test_sos_service import StubPushProvider, StubSmsProvider


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
    rate_limiter = InMemoryRateLimiter()

    async def _override_db_session() -> AsyncIterator[AsyncSession]:
        yield session

    async def _override_service(db_session: SessionDep) -> SosService:
        return SosService(
            sos_events=SosEventRepository(db_session),
            sos_notifications=SosNotificationRepository(db_session),
            contacts=ContactRepository(db_session),
            next_of_kin=NextOfKinRepository(db_session),
            devices=DeviceRepository(db_session),
            users=UserRepository(db_session),
            system_config=SystemConfigRepository(db_session),
            push_provider=StubPushProvider(),
            sms_provider=StubSmsProvider(),
            rate_limiter=rate_limiter,
        )

    app.dependency_overrides[get_db_session] = _override_db_session
    app.dependency_overrides[get_sos_service] = _override_service
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _make_user_with_device(session: AsyncSession) -> tuple[User, Device, str]:
    user = User(
        email=f"{uuid.uuid4()}@example.com",
        phone=f"+27{uuid.uuid4().int % 10**9}",
        display_name="API SOS Test User",
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


async def test_trigger_and_cancel_sos(client: AsyncClient, session: AsyncSession) -> None:
    alice, _d1, alice_token = await _make_user_with_device(session)

    r = await client.post(
        "/api/v1/sos/trigger", json={"last_known_location_ref": "1.0,2.0"},
        headers=_auth(alice_token),
    )
    assert r.status_code == 201, r.text
    event_id = r.json()["id"]
    assert r.json()["status"] == "armed"

    r = await client.post(f"/api/v1/sos/{event_id}/cancel", headers=_auth(alice_token))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"

    r = await client.get("/api/v1/sos", headers=_auth(alice_token))
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1


async def test_escalate_notifies_trusted_circle(
    client: AsyncClient, session: AsyncSession
) -> None:
    alice, _d1, alice_token = await _make_user_with_device(session)
    bob, _d2, _bob_token = await _make_user_with_device(session)
    session.add(Contact(owner_user_id=alice.id, contact_user_id=bob.id, tier="trusted"))
    await session.flush()

    r = await client.post("/api/v1/sos/trigger", json={}, headers=_auth(alice_token))
    event_id = r.json()["id"]

    sos_event = await SosEventRepository(session).get(uuid.UUID(event_id))
    assert sos_event is not None
    sos_event.triggered_at = datetime.now(UTC) - timedelta(seconds=30)
    await session.flush()

    r = await client.post(f"/api/v1/sos/{event_id}/escalate", headers=_auth(alice_token))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "escalated"

    r = await client.get(f"/api/v1/sos/{event_id}/notifications", headers=_auth(alice_token))
    assert r.status_code == 200, r.text
    assert len(r.json()) >= 1


async def test_sos_requires_authentication(client: AsyncClient) -> None:
    r = await client.get("/api/v1/sos")
    assert r.status_code == 401


async def test_trigger_rate_limited_returns_429(
    client: AsyncClient, session: AsyncSession
) -> None:
    """§32 — exercises the real HTTP boundary: RateLimitExceeded raised
    deep in SosService.trigger must surface as 429 with Retry-After via
    the global exception handler in app.main, not a 500."""
    alice, _d1, alice_token = await _make_user_with_device(session)

    for _ in range(SOS_TRIGGER_LIMIT):
        r = await client.post("/api/v1/sos/trigger", json={}, headers=_auth(alice_token))
        assert r.status_code == 201, r.text

    r = await client.post("/api/v1/sos/trigger", json={}, headers=_auth(alice_token))
    assert r.status_code == 429, r.text
    assert "Retry-After" in r.headers
