"""
Unit tests for `AdminMessagingGovernanceService` — real Postgres, real
`MessagingService` underneath (delegated to for the actual remove-
member/delete-message mutations). Same shape as
test_admin_calls_governance.py/test_admin_meetings_governance.py: admin
visibility into conversations platform-wide, and admin override of a
conversation/message the admin isn't a member of.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.domain.admin.messaging_governance import (
    AdminMessagingGovernanceService,
    MessagingGovernanceError,
)
from app.domain.messaging.interfaces import StorageProvider
from app.domain.messaging.service import MessagingService
from app.models.accounts import User
from app.models.circle import Contact
from app.models.devices import Device
from app.repositories.admin import AuditLogRepository
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
    governance: AdminMessagingGovernanceService
    messaging_service: MessagingService
    users: UserRepository
    devices: DeviceRepository
    contacts: ContactRepository
    audit_log: AuditLogRepository


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
    contacts = ContactRepository(session)
    conversations = ConversationRepository(session)
    conversation_members = ConversationMemberRepository(session)
    messages = MessageRepository(session)
    messaging_service = MessagingService(
        identity_keys=IdentityKeyRepository(session),
        signed_prekeys=SignedPrekeyRepository(session),
        one_time_prekeys=OneTimePrekeyRepository(session),
        sender_keys=SenderKeyRepository(session),
        conversations=conversations,
        conversation_members=conversation_members,
        messages=messages,
        message_receipts=MessageReceiptRepository(session),
        media_objects=MediaObjectRepository(session),
        devices=devices,
        blocks=BlockRepository(session),
        contacts=contacts,
        users=users,
        storage_provider=StubStorageProvider(),
        connection_manager=ConnectionManager(),
    )
    audit_log = AuditLogRepository(session)
    governance = AdminMessagingGovernanceService(
        conversations=conversations,
        conversation_members=conversation_members,
        messages=messages,
        users=users,
        devices=devices,
        messaging_service=messaging_service,
        audit_log=audit_log,
    )
    return Harness(
        governance=governance,
        messaging_service=messaging_service,
        users=users,
        devices=devices,
        contacts=contacts,
        audit_log=audit_log,
    )


async def _make_user_with_device(harness: Harness) -> tuple[User, Device]:
    user = await harness.users.add(
        User(
            email=f"{uuid.uuid4()}@example.com",
            phone=f"+27{uuid.uuid4().int % 10**9}",
            display_name="Governance Test User",
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


async def _connect(harness: Harness, user_a_id: uuid.UUID, user_b_id: uuid.UUID) -> None:
    await harness.contacts.add(
        Contact(owner_user_id=user_a_id, contact_user_id=user_b_id, tier="verified")
    )
    await harness.contacts.add(
        Contact(owner_user_id=user_b_id, contact_user_id=user_a_id, tier="verified")
    )


async def test_list_conversations_spans_every_conversation(harness: Harness) -> None:
    alice, _d1 = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
    conversation = await harness.messaging_service.start_direct_conversation(alice.id, bob.id)

    items = await harness.governance.list_conversations(limit=200)
    ids = {i.conversation.id for i in items}
    assert conversation.id in ids
    match = next(i for i in items if i.conversation.id == conversation.id)
    assert match.member_count == 2
    assert match.message_count == 0

    total = await harness.governance.count_conversations()
    assert total >= 1


async def test_get_conversation_detail_includes_member_roles(harness: Harness) -> None:
    alice, alice_device = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
    conversation = await harness.messaging_service.create_group_conversation(alice.id, [bob.id])
    await harness.messaging_service.send_message(
        sender_user_id=alice.id,
        sender_device_id=alice_device.id,
        conversation_id=conversation.id,
        ciphertext=b"hi",
        content_type="text",
        client_message_id=str(uuid.uuid4()),
    )

    detail = await harness.governance.get_conversation(conversation.id)
    assert detail.message_count == 1
    roles = {m.user_id: m.role for m in detail.members}
    assert roles[alice.id] == "admin"
    assert roles[bob.id] == "member"


async def test_get_conversation_rejects_unknown_id(harness: Harness) -> None:
    with pytest.raises(MessagingGovernanceError, match="No such conversation"):
        await harness.governance.get_conversation(uuid.uuid4())


async def test_admin_can_remove_a_member_it_is_not_part_of(harness: Harness) -> None:
    alice, _d1 = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
    conversation = await harness.messaging_service.create_group_conversation(alice.id, [bob.id])

    admin_id = uuid.uuid4()
    await harness.governance.remove_member(
        admin_id=admin_id,
        conversation_id=conversation.id,
        target_user_id=bob.id,
        reason="reported for harassment",
    )

    detail = await harness.governance.get_conversation(conversation.id)
    assert {m.user_id for m in detail.members} == {alice.id}

    entries = await harness.audit_log.list_for_target("conversation", conversation.id)
    entry = next(e for e in entries if e.action == "admin.conversation.member_removed")
    assert entry.actor_id == admin_id
    assert entry.metadata_json == {
        "target_user_id": str(bob.id),
        "reason": "reported for harassment",
    }


async def test_admin_can_delete_a_message_and_never_touches_ciphertext(harness: Harness) -> None:
    alice, alice_device = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
    conversation = await harness.messaging_service.start_direct_conversation(alice.id, bob.id)
    message = await harness.messaging_service.send_message(
        sender_user_id=alice.id,
        sender_device_id=alice_device.id,
        conversation_id=conversation.id,
        ciphertext=b"abusive content",
        content_type="text",
        client_message_id=str(uuid.uuid4()),
    )

    admin_id = uuid.uuid4()
    deleted = await harness.governance.delete_message(
        admin_id=admin_id, message_id=message.id, reason="reported message"
    )
    assert deleted.deleted_at is not None
    assert deleted.ciphertext == b""

    entries = await harness.audit_log.list_for_target("conversation", conversation.id)
    entry = next(e for e in entries if e.action == "admin.message.deleted")
    assert entry.actor_id == admin_id
    assert entry.metadata_json == {"message_id": str(message.id), "reason": "reported message"}


async def test_get_message_context_resolves_sender_without_ciphertext(harness: Harness) -> None:
    alice, alice_device = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
    conversation = await harness.messaging_service.start_direct_conversation(alice.id, bob.id)
    message = await harness.messaging_service.send_message(
        sender_user_id=alice.id,
        sender_device_id=alice_device.id,
        conversation_id=conversation.id,
        ciphertext=b"reported content",
        content_type="text",
        client_message_id=str(uuid.uuid4()),
    )

    context = await harness.governance.get_message_context(message.id)
    assert context.conversation_id == conversation.id
    assert context.sender_user_id == alice.id
    assert context.content_type == "text"
    assert context.deleted_at is None
    assert not hasattr(context, "ciphertext")


async def test_remove_member_rejects_direct_conversations(harness: Harness) -> None:
    alice, _d1 = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)
    await _connect(harness, alice.id, bob.id)
    conversation = await harness.messaging_service.start_direct_conversation(alice.id, bob.id)

    with pytest.raises(MessagingGovernanceError):
        await harness.governance.remove_member(
            admin_id=uuid.uuid4(),
            conversation_id=conversation.id,
            target_user_id=bob.id,
            reason="test",
        )
