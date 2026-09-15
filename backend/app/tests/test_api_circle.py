"""
End-to-end API tests for /circle/* — real Postgres. CircleService has no
external provider dependencies, so only get_db_session needs overriding
(unlike messaging/onboarding, which stub out KYC/OTP/email/storage).
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
        display_name="API Circle Test User",
        date_of_birth=datetime(1990, 1, 1),
        national_id_hash=uuid.uuid4().hex,
        account_state="active",
    )
    session.add(user)
    await session.flush()
    device = Device(
        user_id=user.id,
        device_name="Test Device",
        platform="ios",
        first_seen_at=datetime.now(),
        last_seen_at=datetime.now(),
        is_trusted=True,
    )
    session.add(device)
    await session.flush()
    token = create_access_token(
        user.id, device.id, jwt_secret=get_settings().jwt_secret, ttl_minutes=15
    )
    return user, device, token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_contact_request_accept_and_verify_flow(
    client: AsyncClient, session: AsyncSession
) -> None:
    alice, _d1, alice_token = await _make_user_with_device(session)
    bob, _d2, bob_token = await _make_user_with_device(session)

    r = await client.post(
        "/api/v1/circle/requests",
        json={"to_user_id": str(bob.id), "channel": "qr"},
        headers=_auth(alice_token),
    )
    assert r.status_code == 201, r.text
    request_id = r.json()["id"]
    assert r.json()["status"] == "pending"

    r = await client.get("/api/v1/circle/requests/incoming", headers=_auth(bob_token))
    assert r.status_code == 200, r.text
    assert [req["id"] for req in r.json()] == [request_id]

    r = await client.post(
        f"/api/v1/circle/requests/{request_id}/accept", headers=_auth(bob_token)
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "accepted"

    r = await client.get("/api/v1/circle/contacts", headers=_auth(alice_token))
    assert r.status_code == 200, r.text
    assert r.json()[0]["tier"] == "verified"

    r = await client.post(
        "/api/v1/circle/safety-number/verify",
        json={"contact_user_id": str(bob.id)},
        headers=_auth(alice_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["tier"] == "trusted"

    r = await client.get("/api/v1/circle", headers=_auth(alice_token))
    assert r.status_code == 200, r.text
    assert [c["contact_user_id"] for c in r.json()] == [str(bob.id)]


async def test_decline_contact_request(client: AsyncClient, session: AsyncSession) -> None:
    alice, _d1, alice_token = await _make_user_with_device(session)
    bob, _d2, bob_token = await _make_user_with_device(session)

    r = await client.post(
        "/api/v1/circle/requests",
        json={"to_user_id": str(bob.id), "channel": "qr"},
        headers=_auth(alice_token),
    )
    request_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/circle/requests/{request_id}/decline", headers=_auth(bob_token)
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "declined"


async def test_block_prevents_new_conversation_and_contact_request(
    client: AsyncClient, session: AsyncSession
) -> None:
    alice, _d1, alice_token = await _make_user_with_device(session)
    bob, _d2, _bob_token = await _make_user_with_device(session)

    r = await client.post(f"/api/v1/circle/block/{bob.id}", json={}, headers=_auth(alice_token))
    assert r.status_code == 204, r.text

    r = await client.post(
        "/api/v1/messaging/conversations/direct",
        json={"other_user_id": str(bob.id)},
        headers=_auth(alice_token),
    )
    assert r.status_code == 400

    r = await client.delete(f"/api/v1/circle/block/{bob.id}", headers=_auth(alice_token))
    assert r.status_code == 204, r.text

    # Unblocked, but still no accepted contact — messaging stays gated.
    r = await client.post(
        "/api/v1/messaging/conversations/direct",
        json={"other_user_id": str(bob.id)},
        headers=_auth(alice_token),
    )
    assert r.status_code == 400
    assert "Circle contact request" in r.text


async def test_report_user(client: AsyncClient, session: AsyncSession) -> None:
    alice, _d1, alice_token = await _make_user_with_device(session)
    bob, _d2, _bob_token = await _make_user_with_device(session)

    r = await client.post(
        "/api/v1/circle/report",
        json={"reported_user_id": str(bob.id), "reason": "Harassment"},
        headers=_auth(alice_token),
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "open"


async def test_create_invitation(client: AsyncClient, session: AsyncSession) -> None:
    alice, _d1, alice_token = await _make_user_with_device(session)

    r = await client.post(
        "/api/v1/circle/invitations", json={"channel": "sms"}, headers=_auth(alice_token)
    )
    assert r.status_code == 201, r.text
    assert len(r.json()["invite_code"]) == 10


async def test_circle_requires_authentication(client: AsyncClient) -> None:
    r = await client.get("/api/v1/circle/contacts")
    assert r.status_code == 401
