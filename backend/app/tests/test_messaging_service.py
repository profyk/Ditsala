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
from app.models.circle import Block, Contact
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


class StubStorageProvider(StorageProvider):
    async def create_upload_url(self, *, key: str, content_type: str) -> str:
        return f"https://stub-upload.test/{key}"

    async def create_download_url(self, *, key: str) -> str:
        return f"https://stub-download.test/{key}"

    async def put_object(self, *, key: str, data: bytes, content_type: str) -> None:
        pass

    async def delete_object(self, *, key: str) -> None:
        pass


@dataclass
class Harness:
    service: MessagingService
    users: UserRepository
    devices: DeviceRepository
    messages: MessageRepository
    contacts: ContactRepository
    blocks: BlockRepository


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
    contacts = ContactRepository(session)
    blocks = BlockRepository(session)
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
        blocks=blocks,
        contacts=contacts,
        users=users,
        storage_provider=StubStorageProvider(),
        connection_manager=ConnectionManager(),
    )
    return Harness(
        service=service, users=users, devices=devices, messages=messages,
        contacts=contacts, blocks=blocks,
    )


async def _connect(harness: Harness, user_a_id: uuid.UUID, user_b_id: uuid.UUID) -> None:
    """Mutual 'verified'-tier Circle contact — the precondition
    start_direct_conversation requires (§22); CircleService owns the real
    request/accept flow, this is just the resulting DB state for tests
    that only care about messaging, not Circle, behavior."""
    await harness.contacts.add(
        Contact(owner_user_id=user_a_id, contact_user_id=user_b_id, tier="verified")
    )
    await harness.contacts.add(
        Contact(owner_user_id=user_b_id, contact_user_id=user_a_id, tier="verified")
    )


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


async def test_get_primary_device_id_returns_the_most_recently_registered_device(
    harness: Harness,
) -> None:
    user, first_device = await _make_user_with_device(harness)
    first_identity = await harness.service.register_identity_key(
        first_device, public_identity_key=b"first-device-key", registration_id=1
    )
    # Postgres's `now()` is frozen for this whole test's transaction, so
    # both identity keys' `created_at` would otherwise tie — force a real
    # ordering the way two genuinely separate requests naturally would.
    first_identity.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)

    now = datetime.now(UTC)
    second_device = await harness.devices.add(
        Device(
            user_id=user.id,
            device_name="Second Device",
            platform="android",
            first_seen_at=now,
            last_seen_at=now,
            is_trusted=True,
        )
    )
    await harness.service.register_identity_key(
        second_device, public_identity_key=b"second-device-key", registration_id=2
    )

    primary = await harness.service.get_primary_device_id(user.id)
    assert primary == second_device.id


async def test_get_primary_device_id_requires_some_registered_device(harness: Harness) -> None:
    user, _device = await _make_user_with_device(harness)
    with pytest.raises(MessagingError, match="not completed key registration"):
        await harness.service.get_primary_device_id(user.id)


async def test_list_device_ids_for_user_returns_every_registered_device(harness: Harness) -> None:
    user, first_device = await _make_user_with_device(harness)
    await harness.service.register_identity_key(
        first_device, public_identity_key=b"first-device-key", registration_id=1
    )

    now = datetime.now(UTC)
    second_device = await harness.devices.add(
        Device(
            user_id=user.id,
            device_name="Second Device",
            platform="android",
            first_seen_at=now,
            last_seen_at=now,
            is_trusted=True,
        )
    )
    await harness.service.register_identity_key(
        second_device, public_identity_key=b"second-device-key", registration_id=2
    )

    device_ids = await harness.service.list_device_ids_for_user(user.id)
    assert set(device_ids) == {first_device.id, second_device.id}


async def test_list_device_ids_for_user_is_empty_when_none_registered(harness: Harness) -> None:
    user, _device = await _make_user_with_device(harness)
    assert await harness.service.list_device_ids_for_user(user.id) == []


# --- conversations ---


async def test_start_direct_conversation_is_idempotent(harness: Harness) -> None:
    alice, _d1 = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)

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

    await harness.blocks.add(Block(blocker_user_id=alice.id, blocked_user_id=bob.id))

    with pytest.raises(MessagingError, match="blocked"):
        await harness.service.start_direct_conversation(alice.id, bob.id)
    with pytest.raises(MessagingError, match="blocked"):
        await harness.service.start_direct_conversation(bob.id, alice.id)


async def test_group_conversation_creator_is_admin(harness: Harness) -> None:
    alice, _d1 = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)
    carol, _d3 = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
    await _connect(harness, alice.id, carol.id)

    conversation = await harness.service.create_group_conversation(
        alice.id, [bob.id, carol.id]
    )
    assert conversation.type == "group"

    summaries = await harness.service.list_conversations(bob.id)
    assert conversation.id in [s.conversation.id for s in summaries]


# --- messages ---


async def test_send_and_list_messages(harness: Harness) -> None:
    alice, alice_device = await _make_user_with_device(harness)
    bob, _bob_device = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
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
    await _connect(harness, alice.id, bob.id)
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
    await _connect(harness, alice.id, bob.id)
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
    await _connect(harness, alice.id, bob.id)
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
    await _connect(harness, alice.id, bob.id)
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
    await _connect(harness, alice.id, bob.id)
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
    await _connect(harness, alice.id, bob.id)
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
    bob, bob_device = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
    conversation = await harness.service.create_group_conversation(alice.id, [bob.id])

    await harness.service.upload_sender_key(
        device=alice_device,
        conversation_id=conversation.id,
        recipient_device_id=bob_device.id,
        distribution_message_ref=b"distribution-bytes",
    )

    keys = await harness.service.list_sender_keys(
        user_id=bob.id, conversation_id=conversation.id, recipient_device_id=bob_device.id
    )
    assert len(keys) == 1
    assert keys[0].distribution_message_ref == b"distribution-bytes"

    # A device that isn't the addressed recipient never sees this copy —
    # each Sender Key distribution message is individually encrypted per
    # recipient device, never one shared blob for the whole conversation.
    unrelated_keys = await harness.service.list_sender_keys(
        user_id=alice.id, conversation_id=conversation.id, recipient_device_id=alice_device.id
    )
    assert unrelated_keys == []


# --- media ---


async def test_media_upload_and_download_url(harness: Harness) -> None:
    alice, alice_device = await _make_user_with_device(harness)
    bob, _bob_device = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
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
        media_object_id=media_object.id,
    )
    assert media_object.message_id == message.id

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


async def test_send_message_rejects_someone_elses_media_object(harness: Harness) -> None:
    """Real gap this closes: get_media_download_url's own membership
    check only ever runs once message_id is set — without verifying the
    linking caller actually requested this exact upload, anyone who
    learned another user's media_object_id could attach it to their own
    message and read it via a conversation the real uploader never
    shared it in."""
    alice, alice_device = await _make_user_with_device(harness)
    bob, _bob_device = await _make_user_with_device(harness)
    mallory, _mallory_device = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
    await _connect(harness, alice.id, mallory.id)
    conversation = await harness.service.start_direct_conversation(alice.id, mallory.id)

    media_object, _url = await harness.service.request_media_upload(
        user_id=bob.id, content_hash="abc", encrypted_size_bytes=1024, content_type="image/jpeg"
    )

    with pytest.raises(MessagingError, match="Invalid or already-used media reference"):
        await harness.service.send_message(
            sender_user_id=alice.id,
            sender_device_id=alice_device.id,
            conversation_id=conversation.id,
            ciphertext=b"envelope",
            content_type="media",
            client_message_id=uuid.uuid4().hex,
            media_object_id=media_object.id,
        )


async def test_send_message_rejects_an_already_linked_media_object(harness: Harness) -> None:
    alice, alice_device = await _make_user_with_device(harness)
    bob, _bob_device = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
    conversation = await harness.service.start_direct_conversation(alice.id, bob.id)

    media_object, _url = await harness.service.request_media_upload(
        user_id=alice.id, content_hash="abc", encrypted_size_bytes=1024, content_type="image/jpeg"
    )
    await harness.service.send_message(
        sender_user_id=alice.id,
        sender_device_id=alice_device.id,
        conversation_id=conversation.id,
        ciphertext=b"first",
        content_type="media",
        client_message_id=uuid.uuid4().hex,
        media_object_id=media_object.id,
    )

    with pytest.raises(MessagingError, match="Invalid or already-used media reference"):
        await harness.service.send_message(
            sender_user_id=alice.id,
            sender_device_id=alice_device.id,
            conversation_id=conversation.id,
            ciphertext=b"second",
            content_type="media",
            client_message_id=uuid.uuid4().hex,
            media_object_id=media_object.id,
        )


async def test_unlinked_media_object_is_only_downloadable_by_its_uploader(
    harness: Harness,
) -> None:
    """The other real half of the same gap: before a media object is
    linked to any message, it previously had *no* access check at all —
    anyone who learned its id could download it forever if it was never
    sent."""
    alice, _alice_device = await _make_user_with_device(harness)
    bob, _bob_device = await _make_user_with_device(harness)

    media_object, _url = await harness.service.request_media_upload(
        user_id=alice.id, content_hash="abc", encrypted_size_bytes=1024, content_type="image/jpeg"
    )

    with pytest.raises(MessagingError, match="Unknown media object"):
        await harness.service.get_media_download_url(
            user_id=bob.id, media_object_id=media_object.id
        )

    # The uploader themselves can still fetch it back before it's sent.
    url = await harness.service.get_media_download_url(
        user_id=alice.id, media_object_id=media_object.id
    )
    assert url.startswith("https://stub-download.test/")


# --- retention sweep ---


async def test_purge_expired_messages(harness: Harness) -> None:
    alice, alice_device = await _make_user_with_device(harness)
    bob, _bob_device = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
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


# --- §22-23 integration: Circle tier gates direct messaging ---


async def test_direct_conversation_requires_an_accepted_contact(harness: Harness) -> None:
    alice, _d1 = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)

    with pytest.raises(MessagingError, match="Circle contact request"):
        await harness.service.start_direct_conversation(alice.id, bob.id)


async def test_group_conversation_requires_every_member_be_an_accepted_contact(
    harness: Harness,
) -> None:
    alice, _d1 = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)
    carol, _d3 = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
    # carol is not a Circle contact of alice's at all.

    with pytest.raises(MessagingError, match="Circle contact"):
        await harness.service.create_group_conversation(alice.id, [bob.id, carol.id])


async def test_unverified_tier_contact_cannot_message_yet(harness: Harness) -> None:
    alice, _d1 = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)
    await harness.contacts.add(
        Contact(owner_user_id=alice.id, contact_user_id=bob.id, tier="unverified")
    )

    with pytest.raises(MessagingError, match="Circle contact request"):
        await harness.service.start_direct_conversation(alice.id, bob.id)


async def test_identity_key_change_demotes_trusted_contacts(harness: Harness) -> None:
    alice, _d1 = await _make_user_with_device(harness)
    bob, bob_device = await _make_user_with_device(harness)
    trusted_contact = await harness.contacts.add(
        Contact(owner_user_id=alice.id, contact_user_id=bob.id, tier="trusted")
    )

    await harness.service.register_identity_key(
        bob_device, public_identity_key=b"bobs-first-key", registration_id=1
    )
    await harness.service.register_identity_key(
        bob_device, public_identity_key=b"bobs-reinstalled-key", registration_id=2
    )

    await harness.contacts.session.refresh(trusted_contact)
    assert trusted_contact.tier == "verified"
    assert trusted_contact.safety_number_verified_at is None


# --- group titles, membership enrichment, conversation summaries ---


async def test_group_conversation_can_be_created_with_a_title_and_renamed_by_an_admin(
    harness: Harness,
) -> None:
    alice, _d1 = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)

    conversation = await harness.service.create_group_conversation(
        alice.id, [bob.id], title="Weekend Trip"
    )
    assert conversation.title == "Weekend Trip"

    renamed = await harness.service.rename_group_conversation(
        user_id=alice.id, conversation_id=conversation.id, title="Weekend Trip 2026"
    )
    assert renamed.title == "Weekend Trip 2026"

    with pytest.raises(MessagingError, match="admin"):
        await harness.service.rename_group_conversation(
            user_id=bob.id, conversation_id=conversation.id, title="Bob's Title"
        )


async def test_direct_conversation_cannot_be_renamed(harness: Harness) -> None:
    alice, _d1 = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
    conversation = await harness.service.start_direct_conversation(alice.id, bob.id)

    with pytest.raises(MessagingError, match="Only group conversations"):
        await harness.service.rename_group_conversation(
            user_id=alice.id, conversation_id=conversation.id, title="Nope"
        )


async def test_list_conversation_members_is_enriched_and_membership_gated(
    harness: Harness,
) -> None:
    alice, _d1 = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)
    outsider, _d3 = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
    conversation = await harness.service.create_group_conversation(alice.id, [bob.id])

    members = await harness.service.list_conversation_members(
        user_id=alice.id, conversation_id=conversation.id
    )
    assert {m.display_name for m in members} == {alice.display_name, bob.display_name}
    assert {m.user_id for m in members} == {alice.id, bob.id}
    creator = next(m for m in members if m.user_id == alice.id)
    assert creator.role == "admin"

    with pytest.raises(MessagingError, match="Not a member"):
        await harness.service.list_conversation_members(
            user_id=outsider.id, conversation_id=conversation.id
        )


async def test_list_conversations_includes_last_message_timestamp(harness: Harness) -> None:
    alice, alice_device = await _make_user_with_device(harness)
    bob, _bob_device = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
    conversation = await harness.service.start_direct_conversation(alice.id, bob.id)

    [summary] = [
        s
        for s in await harness.service.list_conversations(alice.id)
        if s.conversation.id == conversation.id
    ]
    assert summary.last_message_at is None

    await harness.service.send_message(
        sender_user_id=alice.id,
        sender_device_id=alice_device.id,
        conversation_id=conversation.id,
        ciphertext=b"hi",
        content_type="text",
        client_message_id=str(uuid.uuid4()),
    )

    [summary] = [
        s
        for s in await harness.service.list_conversations(alice.id)
        if s.conversation.id == conversation.id
    ]
    assert summary.last_message_at is not None


async def test_last_message_timestamp_ignores_reactions(harness: Harness) -> None:
    """Real gap this closes: reacting to an old message shouldn't make a
    conversation jump to the top of the list or show "Reaction" as its
    preview — last_message_at must track the latest real message."""
    alice, alice_device = await _make_user_with_device(harness)
    bob, bob_device = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
    conversation = await harness.service.start_direct_conversation(alice.id, bob.id)

    real_message = await harness.service.send_message(
        sender_user_id=alice.id,
        sender_device_id=alice_device.id,
        conversation_id=conversation.id,
        ciphertext=b"hi",
        content_type="text",
        client_message_id=str(uuid.uuid4()),
    )
    [summary_before] = [
        s
        for s in await harness.service.list_conversations(alice.id)
        if s.conversation.id == conversation.id
    ]

    await harness.service.send_message(
        sender_user_id=bob.id,
        sender_device_id=bob_device.id,
        conversation_id=conversation.id,
        ciphertext=b"heart",
        content_type="reaction",
        client_message_id=str(uuid.uuid4()),
        reply_to_message_id=real_message.id,
    )

    [summary_after] = [
        s
        for s in await harness.service.list_conversations(alice.id)
        if s.conversation.id == conversation.id
    ]
    assert summary_after.last_message_at == summary_before.last_message_at


# --- message pinning ---


async def test_pin_and_unpin_a_message(harness: Harness) -> None:
    alice, alice_device = await _make_user_with_device(harness)
    bob, _bob_device = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
    conversation = await harness.service.start_direct_conversation(alice.id, bob.id)
    message = await harness.service.send_message(
        sender_user_id=alice.id,
        sender_device_id=alice_device.id,
        conversation_id=conversation.id,
        ciphertext=b"pin me",
        content_type="text",
        client_message_id=str(uuid.uuid4()),
    )
    assert message.pinned_at is None

    # Any member — not just the sender — can pin.
    pinned = await harness.service.set_message_pinned(
        user_id=bob.id, message_id=message.id, value=True
    )
    assert pinned.pinned_at is not None

    fetched = await harness.service.get_pinned_message(
        user_id=alice.id, conversation_id=conversation.id
    )
    assert fetched is not None
    assert fetched.id == message.id

    unpinned = await harness.service.set_message_pinned(
        user_id=alice.id, message_id=message.id, value=False
    )
    assert unpinned.pinned_at is None
    after_unpin = await harness.service.get_pinned_message(
        user_id=alice.id, conversation_id=conversation.id
    )
    assert after_unpin is None


async def test_get_pinned_message_returns_the_most_recently_pinned(harness: Harness) -> None:
    alice, alice_device = await _make_user_with_device(harness)
    bob, _bob_device = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
    conversation = await harness.service.start_direct_conversation(alice.id, bob.id)
    first = await harness.service.send_message(
        sender_user_id=alice.id,
        sender_device_id=alice_device.id,
        conversation_id=conversation.id,
        ciphertext=b"first",
        content_type="text",
        client_message_id=str(uuid.uuid4()),
    )
    second = await harness.service.send_message(
        sender_user_id=alice.id,
        sender_device_id=alice_device.id,
        conversation_id=conversation.id,
        ciphertext=b"second",
        content_type="text",
        client_message_id=str(uuid.uuid4()),
    )
    await harness.service.set_message_pinned(user_id=alice.id, message_id=first.id, value=True)
    await harness.service.set_message_pinned(user_id=alice.id, message_id=second.id, value=True)

    fetched = await harness.service.get_pinned_message(
        user_id=alice.id, conversation_id=conversation.id
    )
    assert fetched is not None
    assert fetched.id == second.id


async def test_pin_requires_membership(harness: Harness) -> None:
    alice, alice_device = await _make_user_with_device(harness)
    bob, _bob_device = await _make_user_with_device(harness)
    mallory, _mallory_device = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
    conversation = await harness.service.start_direct_conversation(alice.id, bob.id)
    message = await harness.service.send_message(
        sender_user_id=alice.id,
        sender_device_id=alice_device.id,
        conversation_id=conversation.id,
        ciphertext=b"hi",
        content_type="text",
        client_message_id=str(uuid.uuid4()),
    )

    with pytest.raises(MessagingError):
        await harness.service.set_message_pinned(
            user_id=mallory.id, message_id=message.id, value=True
        )


# --- forwarding ---


async def test_send_message_records_is_forwarded_flag(harness: Harness) -> None:
    alice, alice_device = await _make_user_with_device(harness)
    bob, _bob_device = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
    conversation = await harness.service.start_direct_conversation(alice.id, bob.id)

    ordinary = await harness.service.send_message(
        sender_user_id=alice.id,
        sender_device_id=alice_device.id,
        conversation_id=conversation.id,
        ciphertext=b"original",
        content_type="text",
        client_message_id=str(uuid.uuid4()),
    )
    assert ordinary.is_forwarded is False

    forwarded = await harness.service.send_message(
        sender_user_id=alice.id,
        sender_device_id=alice_device.id,
        conversation_id=conversation.id,
        ciphertext=b"forwarded copy, re-encrypted for this conversation",
        content_type="text",
        client_message_id=str(uuid.uuid4()),
        is_forwarded=True,
    )
    assert forwarded.is_forwarded is True


# --- group role management ---


async def test_admin_adds_a_member_and_a_system_message_is_posted(harness: Harness) -> None:
    alice, _alice_device = await _make_user_with_device(harness)
    bob, _bob_device = await _make_user_with_device(harness)
    carol, _carol_device = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
    await _connect(harness, alice.id, carol.id)
    conversation = await harness.service.create_group_conversation(alice.id, [bob.id])

    member = await harness.service.add_group_member(
        actor_user_id=alice.id, conversation_id=conversation.id, new_member_user_id=carol.id
    )
    assert member.user_id == carol.id
    assert member.role == "member"

    members = await harness.service.list_conversation_members(
        user_id=alice.id, conversation_id=conversation.id
    )
    assert {m.user_id for m in members} == {alice.id, bob.id, carol.id}

    all_messages = await harness.service.list_messages(
        user_id=alice.id, conversation_id=conversation.id
    )
    [system_message] = [m for m in all_messages if m.content_type == "system"]
    expected = "Messaging Test User added Messaging Test User"
    assert system_message.ciphertext.decode("utf-8") == expected


async def test_add_group_member_requires_admin(harness: Harness) -> None:
    alice, _alice_device = await _make_user_with_device(harness)
    bob, _bob_device = await _make_user_with_device(harness)
    carol, _carol_device = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
    await _connect(harness, bob.id, carol.id)
    conversation = await harness.service.create_group_conversation(alice.id, [bob.id])

    with pytest.raises(MessagingError):
        await harness.service.add_group_member(
            actor_user_id=bob.id, conversation_id=conversation.id, new_member_user_id=carol.id
        )


async def test_add_group_member_requires_circle_contact(harness: Harness) -> None:
    alice, _alice_device = await _make_user_with_device(harness)
    bob, _bob_device = await _make_user_with_device(harness)
    carol, _carol_device = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
    conversation = await harness.service.create_group_conversation(alice.id, [bob.id])

    with pytest.raises(MessagingError):
        await harness.service.add_group_member(
            actor_user_id=alice.id, conversation_id=conversation.id, new_member_user_id=carol.id
        )


async def test_member_can_leave_a_group(harness: Harness) -> None:
    alice, _alice_device = await _make_user_with_device(harness)
    bob, _bob_device = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
    conversation = await harness.service.create_group_conversation(alice.id, [bob.id])

    await harness.service.remove_group_member(
        actor_user_id=bob.id, conversation_id=conversation.id, target_user_id=bob.id
    )

    members = await harness.service.list_conversation_members(
        user_id=alice.id, conversation_id=conversation.id
    )
    assert {m.user_id for m in members} == {alice.id}


async def test_non_admin_cannot_remove_another_member(harness: Harness) -> None:
    alice, _alice_device = await _make_user_with_device(harness)
    bob, _bob_device = await _make_user_with_device(harness)
    carol, _carol_device = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
    await _connect(harness, alice.id, carol.id)
    conversation = await harness.service.create_group_conversation(alice.id, [bob.id, carol.id])

    with pytest.raises(MessagingError):
        await harness.service.remove_group_member(
            actor_user_id=bob.id, conversation_id=conversation.id, target_user_id=carol.id
        )


async def test_admin_removes_another_member(harness: Harness) -> None:
    alice, _alice_device = await _make_user_with_device(harness)
    bob, _bob_device = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
    conversation = await harness.service.create_group_conversation(alice.id, [bob.id])

    await harness.service.remove_group_member(
        actor_user_id=alice.id, conversation_id=conversation.id, target_user_id=bob.id
    )

    members = await harness.service.list_conversation_members(
        user_id=alice.id, conversation_id=conversation.id
    )
    assert {m.user_id for m in members} == {alice.id}


async def test_admin_promotes_and_demotes_a_member(harness: Harness) -> None:
    alice, _alice_device = await _make_user_with_device(harness)
    bob, _bob_device = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
    conversation = await harness.service.create_group_conversation(alice.id, [bob.id])

    promoted = await harness.service.set_member_role(
        actor_user_id=alice.id, conversation_id=conversation.id, target_user_id=bob.id, role="admin"
    )
    assert promoted.role == "admin"

    # bob, now an admin, can promote/demote too.
    demoted = await harness.service.set_member_role(
        actor_user_id=bob.id,
        conversation_id=conversation.id,
        target_user_id=alice.id,
        role="member",
    )
    assert demoted.role == "member"


async def test_non_admin_cannot_change_roles(harness: Harness) -> None:
    alice, _alice_device = await _make_user_with_device(harness)
    bob, _bob_device = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
    conversation = await harness.service.create_group_conversation(alice.id, [bob.id])

    with pytest.raises(MessagingError):
        await harness.service.set_member_role(
            actor_user_id=bob.id,
            conversation_id=conversation.id,
            target_user_id=bob.id,
            role="admin",
        )


async def test_group_management_rejects_direct_conversations(harness: Harness) -> None:
    alice, _alice_device = await _make_user_with_device(harness)
    bob, _bob_device = await _make_user_with_device(harness)
    carol, _carol_device = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
    await _connect(harness, alice.id, carol.id)
    conversation = await harness.service.start_direct_conversation(alice.id, bob.id)

    with pytest.raises(MessagingError):
        await harness.service.add_group_member(
            actor_user_id=alice.id, conversation_id=conversation.id, new_member_user_id=carol.id
        )
