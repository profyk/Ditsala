"""
End-to-end API tests for /calls/* — real Postgres. CallService has no
external provider dependencies, so only get_db_session needs overriding.
WebSocket delivery of call.ringing/call.signal events isn't exercised
here (same ASGITransport limitation as test_api_messaging.py) — the
service-level tests already prove ConnectionManager gets the right
device ids and event shapes; this file covers the REST surface.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.db import get_db_session
from app.core.security import create_access_token
from app.main import app
from app.models.accounts import User
from app.models.devices import Device
from app.models.messaging import Conversation, ConversationMember


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
        display_name="API Calls Test User",
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


async def _make_direct_conversation(
    session: AsyncSession, alice_id: uuid.UUID, bob_id: uuid.UUID
) -> uuid.UUID:
    conversation = Conversation(type="direct", created_by=alice_id)
    session.add(conversation)
    await session.flush()
    now = datetime.now(UTC)
    for uid in (alice_id, bob_id):
        session.add(ConversationMember(conversation_id=conversation.id, user_id=uid, joined_at=now))
    await session.flush()
    return conversation.id


async def test_ice_servers_endpoint(client: AsyncClient, session: AsyncSession) -> None:
    _alice, _d1, alice_token = await _make_user_with_device(session)

    r = await client.get("/api/v1/calls/ice-servers", headers=_auth(alice_token))
    assert r.status_code == 200, r.text
    urls = [s["urls"] for s in r.json()["ice_servers"]]
    assert any(u.startswith("stun:") for u in urls)
    assert any(u.startswith("turn:") for u in urls)


async def test_full_call_flow_with_media_switch(
    client: AsyncClient, session: AsyncSession
) -> None:
    alice, _d1, alice_token = await _make_user_with_device(session)
    bob, _d2, bob_token = await _make_user_with_device(session)
    conversation_id = await _make_direct_conversation(session, alice.id, bob.id)

    r = await client.post(
        "/api/v1/calls",
        json={"conversation_id": str(conversation_id), "call_type": "voice"},
        headers=_auth(alice_token),
    )
    assert r.status_code == 201, r.text
    call_id = r.json()["id"]
    assert r.json()["status"] == "ringing"

    r = await client.post(f"/api/v1/calls/{call_id}/answer", headers=_auth(bob_token))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active"

    r = await client.post(
        f"/api/v1/calls/{call_id}/signal",
        json={"payload": {"kind": "offer", "sdp": "v=0..."}},
        headers=_auth(alice_token),
    )
    assert r.status_code == 204, r.text

    r = await client.post(
        f"/api/v1/calls/{call_id}/switch-media",
        json={"call_type": "video"},
        headers=_auth(alice_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["type"] == "video"

    r = await client.post(f"/api/v1/calls/{call_id}/end", headers=_auth(bob_token))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ended"

    r = await client.get("/api/v1/calls", headers=_auth(alice_token))
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1


async def test_decline_call(client: AsyncClient, session: AsyncSession) -> None:
    alice, _d1, alice_token = await _make_user_with_device(session)
    bob, _d2, bob_token = await _make_user_with_device(session)
    conversation_id = await _make_direct_conversation(session, alice.id, bob.id)

    r = await client.post(
        "/api/v1/calls",
        json={"conversation_id": str(conversation_id), "call_type": "video"},
        headers=_auth(alice_token),
    )
    call_id = r.json()["id"]

    r = await client.post(f"/api/v1/calls/{call_id}/decline", headers=_auth(bob_token))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "declined"


async def test_calls_requires_authentication(client: AsyncClient) -> None:
    r = await client.get("/api/v1/calls")
    assert r.status_code == 401
