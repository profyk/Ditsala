"""
Unit tests for E2EE messaging's backend half — key registration, message
relay, groups, media, block (§6, §18-21). A stub StorageProvider stands in
for S3/MinIO (no local instance run here, see docs/SECURITY_GAPS.md); the
real ConnectionManager is used as-is since with no live WebSocket
connections registered, broadcasting is a safe no-op — this still proves
the service calls it with the right device ids.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.domain.messaging.interfaces import StorageProvider
from app.domain.messaging.service import MessagingError, MessagingService
from app.models.accounts import User
from app.models.devices import Device
from app.repositories.circle import BlockRepository
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


class StubStorageProvider(StorageProvider):
    async def create_upload_url(self, *, key: str, content_type: str) -> str:
        return f"https://stub-upload.test/{key}"

    async def create_download_url(self, *, key: str) -> str:
        return f"https://stub-download.test/{key}"


@dataclass
class Harness:
    service: MessagingService
    users: UserRepository
    devices: DeviceRepository
    messages: MessageRepository


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
    users = UserRepository(session)
    devices = DeviceRepository(session)
    messages = MessageRepository(session)
    service = MessagingService(
        identity_keys=IdentityKeyRepository(session),
        signed_prekeys=SignedPrekeyRepository(session),
        one_time_prekeys=OneTimePrekeyRepository(session),
        sender_keys=SenderKeyRepository(session),
        conversations=ConversationRepository(session),
        conversation_members=ConversationMemberRepository(session),
        messages=messages,
        message_receipts=MessageReceiptRepository(session),
        media_objects=MediaObjectRepository(session),
        devices=devices,
        blocks=BlockRepository(session),
        storage_provider=StubStorageProvider(),
        connection_manager=ConnectionManager(),
    )
    return Harness(service=service, users=users, devices=devices, messages=messages)


async def _make_user_with_device(harness: Harness) -> tuple[User, Device]:
    user = await harness.users.add(
        User(
            email=f"{uuid.uuid4()}@example.com",
            phone=f"+27{uuid.uuid4().int % 10**9}",
            display_name="Messaging Test User",
            date_of_birth=datetime(1990, 1, 1),
            national_id_hash=uuid.uuid4().hex,
            account_state="active",
        )
    )
    now = datetime.now(UTC)
    device = await harness.devices.add(
        Device(
            user_id=user.id,
            device_name="Test Device",
            platform="ios",
            first_seen_at=now,
            last_seen_at=now,
            is_trusted=True,
        )
    )
    return user, device


# --- key registration ---


async def test_register_and_rotate_keys(harness: Harness) -> None:
    _user, device = await _make_user_with_device(harness)

    identity = await harness.service.register_identity_key(
        device, public_identity_key=b"identity-key-bytes", registration_id=42
    )
    assert identity.registration_id == 42

    first_prekey = await harness.service.upload_signed_prekey(
        device, key_id=1, public_key=b"spk-1", signature=b"sig-1"
    )
    assert first_prekey.rotated_at is None

    second_prekey = await harness.service.upload_signed_prekey(
        device, key_id=2, public_key=b"spk-2", signature=b"sig-2"
    )
    assert first_prekey.rotated_at is not None  # rotated out
    assert second_prekey.rotated_at is None

    await harness.service.upload_one_time_prekeys(
        device, keys=[(1, b"otk-1"), (2, b"otk-2")]
    )

    bundle = await harness.service.get_prekey_bundle(user_id=_user.id, device_id=device.id)
    assert bundle.identity_key == b"identity-key-bytes"
    assert bundle.signed_prekey_id == 2  # the current, unrotated one
    assert bundle.one_time_prekey_id in (1, 2)

    # One-time prekeys are consumed exactly once.
    bundle_2 = await harness.service.get_prekey_bundle(user_id=_user.id, device_id=device.id)
    assert bundle_2.one_time_prekey_id != bundle.one_time_prekey_id

    bundle_3 = await harness.service.get_prekey_bundle(user_id=_user.id, device_id=device.id)
    assert bundle_3.one_time_prekey_id is None  # pool exhausted


async def test_prekey_bundle_requires_registered_device(harness: Harness) -> None:
    user, device = await _make_user_with_device(harness)
    with pytest.raises(MessagingError):
        await harness.service.get_prekey_bundle(user_id=user.id, device_id=device.id)


# --- conversations ---


async def test_start_direct_conversation_is_idempotent(harness: Harness) -> None:
    alice, _d1 = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)

    first = await harness.service.start_direct_conversation(alice.id, bob.id)
    second = await harness.service.start_direct_conversation(alice.id, bob.id)
    assert first.id == second.id

    reversed_direction = await harness.service.start_direct_conversation(bob.id, alice.id)
    assert reversed_direction.id == first.id


async def test_cannot_start_conversation_with_self(harness: Harness) -> None:
    alice, _d1 = await _make_user_with_device(harness)
    with pytest.raises(MessagingError, match="yourself"):
        await harness.service.start_direct_conversation(alice.id, alice.id)


async def test_blocked_users_cannot_start_a_conversation(harness: Harness) -> None:
    alice, _d1 = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)

    await harness.service.block_user(user_id=alice.id, target_user_id=bob.id)

    with pytest.raises(MessagingError, match="blocked"):
        await harness.service.start_direct_conversation(alice.id, bob.id)
    with pytest.raises(MessagingError, match="blocked"):
        await harness.service.start_direct_conversation(bob.id, alice.id)


async def test_group_conversation_creator_is_admin(harness: Harness) -> None:
    alice, _d1 = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)
    carol, _d3 = await _make_user_with_device(harness)

    conversation = await harness.service.create_group_conversation(
        alice.id, [bob.id, carol.id]
    )
    assert conversation.type == "group"

    conversations = await harness.service.list_conversations(bob.id)
    assert conversation.id in [c.id for c in conversations]


# --- messages ---


async def test_send_and_list_messages(harness: Harness) -> None:
    alice, alice_device = await _make_user_with_device(harness)
    bob, _bob_device = await _make_user_with_device(harness)
    conversation = await harness.service.start_direct_conversation(alice.id, bob.id)

    message = await harness.service.send_message(
        sender_user_id=alice.id,
        sender_device_id=alice_device.id,
        conversation_id=conversation.id,
        ciphertext=b"opaque-ciphertext",
        content_type="text",
        client_message_id=uuid.uuid4().hex,
    )
    assert message.ciphertext == b"opaque-ciphertext"

    messages = await harness.service.list_messages(user_id=bob.id, conversation_id=conversation.id)
    assert [m.id for m in messages] == [message.id]


async def test_send_message_rejects_non_members(harness: Harness) -> None:
    alice, alice_device = await _make_user_with_device(harness)
    bob, _bob_device = await _make_user_with_device(harness)
    outsider, _o_device = await _make_user_with_device(harness)
    conversation = await harness.service.start_direct_conversation(alice.id, bob.id)

    with pytest.raises(MessagingError, match="Not a member"):
        await harness.service.list_messages(user_id=outsider.id, conversation_id=conversation.id)

    with pytest.raises(MessagingError, match="Not a member"):
        await harness.service.send_message(
            sender_user_id=outsider.id,
            sender_device_id=alice_device.id,
            conversation_id=conversation.id,
            ciphertext=b"x",
            content_type="text",
            client_message_id=uuid.uuid4().hex,
        )


async def test_send_message_is_idempotent(harness: Harness) -> None:
    alice, alice_device = await _make_user_with_device(harness)
    bob, _bob_device = await _make_user_with_device(harness)
    conversation = await harness.service.start_direct_conversation(alice.id, bob.id)
    client_message_id = uuid.uuid4().hex

    first = await harness.service.send_message(
        sender_user_id=alice.id,
        sender_device_id=alice_device.id,
        conversation_id=conversation.id,
        ciphertext=b"one",
        content_type="text",
        client_message_id=client_message_id,
    )
    second = await harness.service.send_message(
        sender_user_id=alice.id,
        sender_device_id=alice_device.id,
        conversation_id=conversation.id,
        ciphertext=b"a-resend-should-be-ignored",
        content_type="text",
        client_message_id=client_message_id,
    )
    assert first.id == second.id
    assert second.ciphertext == b"one"  # the resend's body was ignored


async def test_disappearing_timer_sets_message_expiry(harness: Harness) -> None:
    alice, alice_device = await _make_user_with_device(harness)
    bob, _bob_device = await _make_user_with_device(harness)
    conversation = await harness.service.start_direct_conversation(alice.id, bob.id)

    await harness.service.set_disappearing_timer(
        user_id=alice.id, conversation_id=conversation.id, seconds=3600
    )
    message = await harness.service.send_message(
        sender_user_id=alice.id,
        sender_device_id=alice_device.id,
        conversation_id=conversation.id,
        ciphertext=b"x",
        content_type="text",
        client_message_id=uuid.uuid4().hex,
    )
    assert message.expires_at is not None


async def test_only_sender_can_edit_or_delete(harness: Harness) -> None:
    alice, alice_device = await _make_user_with_device(harness)
    bob, _bob_device = await _make_user_with_device(harness)
    conversation = await harness.service.start_direct_conversation(alice.id, bob.id)
    message = await harness.service.send_message(
        sender_user_id=alice.id,
        sender_device_id=alice_device.id,
        conversation_id=conversation.id,
        ciphertext=b"original",
        content_type="text",
        client_message_id=uuid.uuid4().hex,
    )

    with pytest.raises(MessagingError, match="own messages"):
        await harness.service.edit_message(
            user_id=bob.id, message_id=message.id, new_ciphertext=b"hacked"
        )

    edited = await harness.service.edit_message(
        user_id=alice.id, message_id=message.id, new_ciphertext=b"edited"
    )
    assert edited.ciphertext == b"edited"
    assert edited.edited_at is not None

    with pytest.raises(MessagingError, match="own messages"):
        await harness.service.delete_message(user_id=bob.id, message_id=message.id)

    await harness.service.delete_message(user_id=alice.id, message_id=message.id)
    assert message.deleted_at is not None
    assert message.ciphertext == b""


async def test_mark_receipt_is_idempotent(harness: Harness) -> None:
    alice, alice_device = await _make_user_with_device(harness)
    bob, _bob_device = await _make_user_with_device(harness)
    conversation = await harness.service.start_direct_conversation(alice.id, bob.id)
    message = await harness.service.send_message(
        sender_user_id=alice.id,
        sender_device_id=alice_device.id,
        conversation_id=conversation.id,
        ciphertext=b"x",
        content_type="text",
        client_message_id=uuid.uuid4().hex,
    )

    first = await harness.service.mark_receipt(
        user_id=bob.id, message_id=message.id, status="read"
    )
    second = await harness.service.mark_receipt(
        user_id=bob.id, message_id=message.id, status="read"
    )
    assert first.id == second.id


# --- conversation flags ---


async def test_mute_archive_pin_flags(harness: Harness) -> None:
    alice, _d1 = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)
    conversation = await harness.service.start_direct_conversation(alice.id, bob.id)

    muted_until = datetime.now(UTC) + timedelta(hours=1)
    membership = await harness.service.set_muted(
        user_id=alice.id, conversation_id=conversation.id, muted_until=muted_until
    )
    assert membership.muted_until == muted_until

    membership = await harness.service.set_archived(
        user_id=alice.id, conversation_id=conversation.id, archived=True
    )
    assert membership.archived_at is not None

    membership = await harness.service.set_pinned(
        user_id=alice.id, conversation_id=conversation.id, pinned=True
    )
    assert membership.pinned_at is not None


# --- groups: sender keys ---


async def test_sender_key_upload_and_list(harness: Harness) -> None:
    alice, alice_device = await _make_user_with_device(harness)
    bob, _bob_device = await _make_user_with_device(harness)
    conversation = await harness.service.create_group_conversation(alice.id, [bob.id])

    await harness.service.upload_sender_key(
        device=alice_device,
        conversation_id=conversation.id,
        distribution_message_ref=b"distribution-bytes",
    )

    keys = await harness.service.list_sender_keys(user_id=bob.id, conversation_id=conversation.id)
    assert len(keys) == 1
    assert keys[0].distribution_message_ref == b"distribution-bytes"


# --- media ---


async def test_media_upload_and_download_url(harness: Harness) -> None:
    alice, alice_device = await _make_user_with_device(harness)
    bob, _bob_device = await _make_user_with_device(harness)
    conversation = await harness.service.start_direct_conversation(alice.id, bob.id)

    media_object, upload_url = await harness.service.request_media_upload(
        user_id=alice.id,
        content_hash="abc123",
        encrypted_size_bytes=1024,
        content_type="image/jpeg",
    )
    assert upload_url.startswith("https://stub-upload.test/")

    message = await harness.service.send_message(
        sender_user_id=alice.id,
        sender_device_id=alice_device.id,
        conversation_id=conversation.id,
        ciphertext=b"envelope-with-media-key",
        content_type="media",
        client_message_id=uuid.uuid4().hex,
    )
    media_object.message_id = message.id

    download_url = await harness.service.get_media_download_url(
        user_id=bob.id, media_object_id=media_object.id
    )
    assert download_url.startswith("https://stub-download.test/")


async def test_media_upload_rejects_oversized_files(harness: Harness) -> None:
    alice, _device = await _make_user_with_device(harness)
    with pytest.raises(MessagingError, match="too large"):
        await harness.service.request_media_upload(
            user_id=alice.id,
            content_hash="abc",
            encrypted_size_bytes=200 * 1024 * 1024,
            content_type="video/mp4",
        )


# --- block ---


async def test_block_and_unblock(harness: Harness) -> None:
    alice, _d1 = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)

    await harness.service.block_user(user_id=alice.id, target_user_id=bob.id)
    with pytest.raises(MessagingError, match="blocked"):
        await harness.service.start_direct_conversation(alice.id, bob.id)

    await harness.service.unblock_user(user_id=alice.id, target_user_id=bob.id)
    conversation = await harness.service.start_direct_conversation(alice.id, bob.id)
    assert conversation is not None


# --- retention sweep ---


async def test_purge_expired_messages(harness: Harness) -> None:
    alice, alice_device = await _make_user_with_device(harness)
    bob, _bob_device = await _make_user_with_device(harness)
    conversation = await harness.service.start_direct_conversation(alice.id, bob.id)

    message = await harness.service.send_message(
        sender_user_id=alice.id,
        sender_device_id=alice_device.id,
        conversation_id=conversation.id,
        ciphertext=b"expiring",
        content_type="text",
        client_message_id=uuid.uuid4().hex,
    )
    message.expires_at = datetime.now(UTC) - timedelta(seconds=1)  # already expired

    purged_count = await harness.service.purge_expired_messages()
    assert purged_count == 1
    assert message.deleted_at is not None
    assert message.ciphertext == b""
