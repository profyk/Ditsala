"""
End-to-end API tests for /messaging/* — real Postgres, a stub
StorageProvider swapped in via dependency_overrides (no local S3/MinIO —
see docs/SECURITY_GAPS.md). WebSocket delivery itself isn't exercised
here (httpx's ASGITransport doesn't speak the WS upgrade protocol) — the
service-level tests already prove ConnectionManager gets called with the
right device ids; this file covers the REST surface.
"""

import base64
import uuid
from collections.abc import AsyncIterator
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1.deps import SessionDep, get_messaging_service
from app.core.config import get_settings
from app.core.db import get_db_session
from app.core.security import create_access_token
from app.domain.messaging.service import MessagingService
from app.main import app
from app.models.accounts import User
from app.models.circle import Contact
from app.models.devices import Device
from app.repositories.circle import BlockRepository, ContactRepository
from app.repositories.conversations import ConversationMemberRepository, ConversationRepository
from app.repositories.crypto import (
    IdentityKeyRepository,
    OneTimePrekeyRepository,
    SenderKeyRepository,
    SignedPrekeyRepository,
)
from app.repositories.devices import DeviceRepository
from app.repositories.messages import (
    MediaObjectRepository,
    MessageReceiptRepository,
    MessageRepository,
)
from app.repositories.users import UserRepository
from app.services.realtime.websocket_manager import ConnectionManager
from app.tests.test_messaging_service import StubStorageProvider


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


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

    async def _override_service(db_session: SessionDep) -> MessagingService:
        return MessagingService(
            identity_keys=IdentityKeyRepository(db_session),
            signed_prekeys=SignedPrekeyRepository(db_session),
            one_time_prekeys=OneTimePrekeyRepository(db_session),
            sender_keys=SenderKeyRepository(db_session),
            conversations=ConversationRepository(db_session),
            conversation_members=ConversationMemberRepository(db_session),
            messages=MessageRepository(db_session),
            message_receipts=MessageReceiptRepository(db_session),
            media_objects=MediaObjectRepository(db_session),
            devices=DeviceRepository(db_session),
            blocks=BlockRepository(db_session),
            contacts=ContactRepository(db_session),
            users=UserRepository(db_session),
            storage_provider=StubStorageProvider(),
            connection_manager=ConnectionManager(),
        )

    app.dependency_overrides[get_db_session] = _override_db_session
    app.dependency_overrides[get_messaging_service] = _override_service
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _make_user_with_device(session: AsyncSession) -> tuple[User, Device, str]:
    user = User(
        email=f"{uuid.uuid4()}@example.com",
        phone=f"+27{uuid.uuid4().int % 10**9}",
        display_name="API Messaging Test User",
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


async def _connect(session: AsyncSession, user_a_id: uuid.UUID, user_b_id: uuid.UUID) -> None:
    """Mutual 'verified'-tier Circle contact — the precondition
    /messaging/conversations/direct requires (§22); see test_api_circle.py
    for the real request/accept flow that produces this state."""
    session.add(Contact(owner_user_id=user_a_id, contact_user_id=user_b_id, tier="verified"))
    session.add(Contact(owner_user_id=user_b_id, contact_user_id=user_a_id, tier="verified"))
    await session.flush()


async def test_key_registration_and_prekey_bundle(
    client: AsyncClient, session: AsyncSession
) -> None:
    _user, device, token = await _make_user_with_device(session)

    r = await client.post(
        "/api/v1/messaging/keys/identity",
        json={"public_identity_key": _b64(b"identity"), "registration_id": 7},
        headers=_auth(token),
    )
    assert r.status_code == 204, r.text

    r = await client.post(
        "/api/v1/messaging/keys/signed-prekey",
        json={"key_id": 1, "public_key": _b64(b"spk"), "signature": _b64(b"sig")},
        headers=_auth(token),
    )
    assert r.status_code == 204, r.text

    r = await client.post(
        "/api/v1/messaging/keys/one-time-prekeys",
        json={"keys": [{"key_id": 1, "public_key": _b64(b"otk-1")}]},
        headers=_auth(token),
    )
    assert r.status_code == 204, r.text

    r = await client.get(
        f"/api/v1/messaging/keys/prekey-bundle/{_user.id}/{device.id}", headers=_auth(token)
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert base64.b64decode(body["identity_key"]) == b"identity"
    assert body["one_time_prekey_id"] == 1


async def test_direct_conversation_and_messaging_flow(
    client: AsyncClient, session: AsyncSession
) -> None:
    alice, _alice_device, alice_token = await _make_user_with_device(session)
    bob, _bob_device, bob_token = await _make_user_with_device(session)
    await _connect(session, alice.id, bob.id)

    r = await client.post(
        "/api/v1/messaging/conversations/direct",
        json={"other_user_id": str(bob.id)},
        headers=_auth(alice_token),
    )
    assert r.status_code == 200, r.text
    conversation_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/messaging/conversations/{conversation_id}/messages",
        json={
            "ciphertext": _b64(b"hello"),
            "content_type": "text",
            "client_message_id": uuid.uuid4().hex,
        },
        headers=_auth(alice_token),
    )
    assert r.status_code == 200, r.text
    message_id = r.json()["id"]
    assert base64.b64decode(r.json()["ciphertext"]) == b"hello"

    r = await client.get(
        f"/api/v1/messaging/conversations/{conversation_id}/messages", headers=_auth(bob_token)
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1

    r = await client.post(
        f"/api/v1/messaging/messages/{message_id}/receipts",
        json={"status": "read"},
        headers=_auth(bob_token),
    )
    assert r.status_code == 204, r.text

    r = await client.patch(
        f"/api/v1/messaging/messages/{message_id}",
        json={"ciphertext": _b64(b"edited")},
        headers=_auth(alice_token),
    )
    assert r.status_code == 200, r.text

    r = await client.delete(
        f"/api/v1/messaging/messages/{message_id}", headers=_auth(alice_token)
    )
    assert r.status_code == 204, r.text


async def test_outsider_cannot_read_conversation(
    client: AsyncClient, session: AsyncSession
) -> None:
    alice, _d1, alice_token = await _make_user_with_device(session)
    bob, _d2, _bob_token = await _make_user_with_device(session)
    _outsider, _d3, outsider_token = await _make_user_with_device(session)
    await _connect(session, alice.id, bob.id)

    r = await client.post(
        "/api/v1/messaging/conversations/direct",
        json={"other_user_id": str(bob.id)},
        headers=_auth(alice_token),
    )
    conversation_id = r.json()["id"]

    r = await client.get(
        f"/api/v1/messaging/conversations/{conversation_id}/messages",
        headers=_auth(outsider_token),
    )
    assert r.status_code == 400


async def test_conversation_flags(client: AsyncClient, session: AsyncSession) -> None:
    alice, _d1, alice_token = await _make_user_with_device(session)
    bob, _d2, _bob_token = await _make_user_with_device(session)
    await _connect(session, alice.id, bob.id)

    r = await client.post(
        "/api/v1/messaging/conversations/direct",
        json={"other_user_id": str(bob.id)},
        headers=_auth(alice_token),
    )
    conversation_id = r.json()["id"]

    r = await client.patch(
        f"/api/v1/messaging/conversations/{conversation_id}/archived",
        json={"value": True},
        headers=_auth(alice_token),
    )
    assert r.status_code == 204, r.text

    r = await client.patch(
        f"/api/v1/messaging/conversations/{conversation_id}/pinned",
        json={"value": True},
        headers=_auth(alice_token),
    )
    assert r.status_code == 204, r.text

    r = await client.patch(
        f"/api/v1/messaging/conversations/{conversation_id}/muted",
        json={"muted_until": "2099-01-01T00:00:00Z"},
        headers=_auth(alice_token),
    )
    assert r.status_code == 204, r.text

    # Real regression: setMuted/setArchived/setPinned were write-only —
    # nothing ever read this state back until now.
    r = await client.get("/api/v1/messaging/conversations", headers=_auth(alice_token))
    assert r.status_code == 200, r.text
    listed = next(c for c in r.json() if c["id"] == conversation_id)
    assert listed["archived"] is True
    assert listed["pinned"] is True
    assert listed["muted_until"] is not None

    r = await client.patch(
        f"/api/v1/messaging/conversations/{conversation_id}/disappearing-timer",
        json={"seconds": 3600},
        headers=_auth(alice_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["disappearing_timer_seconds"] == 3600


async def test_group_conversation_and_sender_keys(
    client: AsyncClient, session: AsyncSession
) -> None:
    alice, alice_device, alice_token = await _make_user_with_device(session)
    bob, bob_device, bob_token = await _make_user_with_device(session)
    await _connect(session, alice.id, bob.id)

    r = await client.post(
        "/api/v1/messaging/conversations/group",
        json={"member_ids": [str(bob.id)]},
        headers=_auth(alice_token),
    )
    assert r.status_code == 200, r.text
    conversation_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/messaging/conversations/{conversation_id}/sender-keys",
        json={
            "recipient_device_id": str(bob_device.id),
            "distribution_message_ref": _b64(b"dist-ref"),
        },
        headers=_auth(alice_token),
    )
    assert r.status_code == 204, r.text

    r = await client.get(
        f"/api/v1/messaging/conversations/{conversation_id}/sender-keys", headers=_auth(bob_token)
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1
    assert r.json()[0]["device_id"] == str(alice_device.id)


async def test_media_upload_flow(client: AsyncClient, session: AsyncSession) -> None:
    alice, _d1, alice_token = await _make_user_with_device(session)

    r = await client.post(
        "/api/v1/messaging/media/upload",
        json={"content_hash": "abc", "encrypted_size_bytes": 2048, "content_type": "image/jpeg"},
        headers=_auth(alice_token),
    )
    assert r.status_code == 200, r.text
    media_object_id = r.json()["media_object_id"]
    assert r.json()["upload_url"].startswith("https://stub-upload.test/")

    r = await client.get(
        f"/api/v1/messaging/media/{media_object_id}/download", headers=_auth(alice_token)
    )
    assert r.status_code == 200, r.text
    assert r.json()["download_url"].startswith("https://stub-download.test/")


async def test_messaging_requires_authentication(client: AsyncClient) -> None:
    r = await client.get("/api/v1/messaging/conversations")
    assert r.status_code == 401
