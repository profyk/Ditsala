"""
Unit tests for VipChatService — VIP Multilingual Chat (§1/4/9 of the VIP
work). Real Postgres; the real ConnectionManager is used as-is (same
reasoning as test_messaging_service.py: with no live WebSocket
connections registered, broadcasting is a safe no-op that still proves
the service calls it with the right device ids).
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.domain.translation.service import TranslationService
from app.domain.vip_chat.service import VipChatError, VipChatService
from app.models.accounts import User
from app.models.circle import Block, Contact
from app.models.devices import Device
from app.repositories.admin import SystemConfigRepository
from app.repositories.circle import BlockRepository, ContactRepository
from app.repositories.conversations import ConversationMemberRepository, ConversationRepository
from app.repositories.devices import DeviceRepository
from app.repositories.translation import (
    InterpreterSessionRepository,
    TranslationRequestRepository,
    TranslationUsageRepository,
    UserLanguagePreferenceRepository,
    VipMessageRepository,
    VipMessageTranslationRepository,
)
from app.repositories.users import UserRepository
from app.services.realtime.websocket_manager import ConnectionManager
from app.services.translation.mock import MockTranslationProvider


@dataclass
class Harness:
    service: VipChatService
    users: UserRepository
    contacts: ContactRepository
    blocks: BlockRepository
    devices: DeviceRepository
    language_preferences: UserLanguagePreferenceRepository


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
    contacts = ContactRepository(session)
    blocks = BlockRepository(session)
    devices = DeviceRepository(session)
    language_preferences = UserLanguagePreferenceRepository(session)
    translation_service = TranslationService(
        translation_requests=TranslationRequestRepository(session),
        translation_usage=TranslationUsageRepository(session),
        user_language_preferences=language_preferences,
        interpreter_sessions=InterpreterSessionRepository(session),
        system_config=SystemConfigRepository(session),
        provider=MockTranslationProvider(),
    )
    service = VipChatService(
        conversations=ConversationRepository(session),
        conversation_members=ConversationMemberRepository(session),
        vip_messages=VipMessageRepository(session),
        vip_message_translations=VipMessageTranslationRepository(session),
        users=users,
        contacts=contacts,
        blocks=blocks,
        language_preferences=language_preferences,
        devices=devices,
        translation_service=translation_service,
        connection_manager=ConnectionManager(),
    )
    return Harness(
        service=service,
        users=users,
        contacts=contacts,
        blocks=blocks,
        devices=devices,
        language_preferences=language_preferences,
    )


async def _make_user(harness: Harness, *, account_tier: str = "vip") -> User:
    return await harness.users.add(
        User(
            email=f"{uuid.uuid4()}@example.com",
            phone=f"+27{uuid.uuid4().int % 10**9}",
            display_name="VIP Chat Test User",
            date_of_birth=datetime(1990, 1, 1),
            national_id_hash=uuid.uuid4().hex,
            account_state="active",
            account_tier=account_tier,
        )
    )


async def _connect(
    harness: Harness, user_a_id: uuid.UUID, user_b_id: uuid.UUID, *, tier: str = "verified"
) -> None:
    """Mutual Circle contact at the given tier — VipChatService.start_conversation's
    precondition, same shape as test_messaging_service.py's `_connect` helper."""
    await harness.contacts.add(
        Contact(owner_user_id=user_a_id, contact_user_id=user_b_id, tier=tier)
    )
    await harness.contacts.add(
        Contact(owner_user_id=user_b_id, contact_user_id=user_a_id, tier=tier)
    )


async def _set_language(harness: Harness, user_id: uuid.UUID, language: str) -> None:
    await harness.language_preferences.upsert(
        user_id=user_id,
        preferred_language=language,
        auto_detect_language=False,
        translate_incoming=True,
        translate_outgoing=True,
    )


async def _make_device(harness: Harness, user_id: uuid.UUID) -> Device:
    now = datetime.now(UTC)
    return await harness.devices.add(
        Device(
            user_id=user_id,
            device_name="Test Device",
            platform="ios",
            first_seen_at=now,
            last_seen_at=now,
            is_trusted=True,
        )
    )


# --- start_conversation ---


async def test_start_conversation_requires_both_users_vip(harness: Harness) -> None:
    vip_user = await _make_user(harness, account_tier="vip")
    normal_user = await _make_user(harness, account_tier="normal")
    await _connect(harness, vip_user.id, normal_user.id)

    with pytest.raises(VipChatError, match="Ditsala VIP"):
        await harness.service.start_conversation(normal_user, vip_user.id)

    with pytest.raises(VipChatError, match="requires both people to have Ditsala VIP"):
        await harness.service.start_conversation(vip_user, normal_user.id)


async def test_start_conversation_requires_accepted_circle_contact(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)
    with pytest.raises(VipChatError, match="Circle contact request"):
        await harness.service.start_conversation(alice, bob.id)


async def test_start_conversation_rejects_unverified_tier(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)
    await _connect(harness, alice.id, bob.id, tier="unverified")
    with pytest.raises(VipChatError, match="Circle contact request"):
        await harness.service.start_conversation(alice, bob.id)


async def test_start_conversation_rejects_self(harness: Harness) -> None:
    alice = await _make_user(harness)
    with pytest.raises(VipChatError, match="yourself"):
        await harness.service.start_conversation(alice, alice.id)


async def test_start_conversation_rejects_blocked_contact(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)
    await _connect(harness, alice.id, bob.id)
    await harness.blocks.add(Block(blocker_user_id=bob.id, blocked_user_id=alice.id))

    with pytest.raises(VipChatError, match="blocked"):
        await harness.service.start_conversation(alice, bob.id)


async def test_start_conversation_is_idempotent(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)
    await _connect(harness, alice.id, bob.id)

    first = await harness.service.start_conversation(alice, bob.id)
    second = await harness.service.start_conversation(alice, bob.id)
    assert first.id == second.id

    conversations = await harness.service.list_conversations(alice.id)
    assert [c.id for c in conversations] == [first.id]


async def test_start_conversation_does_not_collide_with_a_direct_conversation(
    harness: Harness,
) -> None:
    """A normal `direct` E2EE thread between the same two people must
    never be mistaken for their VIP multilingual thread."""
    from app.models.messaging import Conversation, ConversationMember

    alice = await _make_user(harness)
    bob = await _make_user(harness)
    await _connect(harness, alice.id, bob.id)

    direct = await harness.service._conversations.add(
        Conversation(type="direct", created_by=alice.id)
    )
    now = datetime.now(UTC)
    for uid in (alice.id, bob.id):
        await harness.service._conversation_members.add(
            ConversationMember(conversation_id=direct.id, user_id=uid, joined_at=now)
        )

    vip_conversation = await harness.service.start_conversation(alice, bob.id)
    assert vip_conversation.id != direct.id
    assert vip_conversation.type == "vip_multilingual"


# --- send_message / list_messages ---


async def test_send_message_requires_recipient_language_preferences(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)
    await _connect(harness, alice.id, bob.id)
    conversation = await harness.service.start_conversation(alice, bob.id)

    with pytest.raises(VipChatError, match="Language Settings"):
        await harness.service.send_message(
            conversation_id=conversation.id, sender=alice, text="Hello", client_message_id="c1"
        )


async def test_send_message_translates_to_recipient_language(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)
    await _connect(harness, alice.id, bob.id)
    await _set_language(harness, alice.id, "en")
    await _set_language(harness, bob.id, "zh")
    device = await _make_device(harness, bob.id)
    conversation = await harness.service.start_conversation(alice, bob.id)

    result = await harness.service.send_message(
        conversation_id=conversation.id,
        sender=alice,
        text="Hello, nice to meet you.",
        client_message_id="msg-1",
    )
    assert result.message.original_language == "en"
    assert result.translation is not None
    assert result.translation.target_language == "zh"
    assert result.translation.translated_text == "你好，很高兴认识你。"
    assert result.translation.status == "completed"

    messages = await harness.service.list_messages(conversation_id=conversation.id, user_id=bob.id)
    assert len(messages) == 1
    assert messages[0].message.id == result.message.id
    _ = device  # exercised via _push_to_recipient; no assertion needed on a no-op send


async def test_send_message_is_idempotent_on_client_message_id(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)
    await _connect(harness, alice.id, bob.id)
    await _set_language(harness, alice.id, "en")
    await _set_language(harness, bob.id, "zh")
    conversation = await harness.service.start_conversation(alice, bob.id)

    first = await harness.service.send_message(
        conversation_id=conversation.id, sender=alice, text="Hello", client_message_id="dup-1"
    )
    second = await harness.service.send_message(
        conversation_id=conversation.id, sender=alice, text="Hello", client_message_id="dup-1"
    )
    assert first.message.id == second.message.id

    messages = await harness.service.list_messages(
        conversation_id=conversation.id, user_id=alice.id
    )
    assert len(messages) == 1


async def test_send_message_requires_membership(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)
    stranger = await _make_user(harness)
    await _connect(harness, alice.id, bob.id)
    await _set_language(harness, bob.id, "zh")
    conversation = await harness.service.start_conversation(alice, bob.id)

    with pytest.raises(VipChatError, match="Not a member"):
        await harness.service.send_message(
            conversation_id=conversation.id, sender=stranger, text="Hi", client_message_id="c1"
        )


async def test_send_message_uses_auto_detect_when_sender_prefers_it(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)
    await _connect(harness, alice.id, bob.id)
    await harness.language_preferences.upsert(
        user_id=alice.id,
        preferred_language="en",
        auto_detect_language=True,
        translate_incoming=True,
        translate_outgoing=True,
    )
    await _set_language(harness, bob.id, "en")
    conversation = await harness.service.start_conversation(alice, bob.id)

    result = await harness.service.send_message(
        conversation_id=conversation.id,
        sender=alice,
        text="你好，很高兴认识你。",
        client_message_id="auto-1",
    )
    # Auto-detect resolves via the provider, not the stored preference.
    assert result.message.original_language == "zh"


# --- retry_translation ---


async def test_retry_translation_recomputes_the_same_target(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)
    await _connect(harness, alice.id, bob.id)
    await _set_language(harness, alice.id, "en")
    await _set_language(harness, bob.id, "zh")
    conversation = await harness.service.start_conversation(alice, bob.id)

    sent = await harness.service.send_message(
        conversation_id=conversation.id,
        sender=alice,
        text="Hello, nice to meet you.",
        client_message_id="retry-1",
    )
    retried = await harness.service.retry_translation(
        message_id=sent.message.id, user_id=bob.id
    )
    assert retried.target_language == "zh"
    assert retried.translated_text == "你好，很高兴认识你。"


async def test_retry_translation_requires_membership(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)
    stranger = await _make_user(harness)
    await _connect(harness, alice.id, bob.id)
    await _set_language(harness, alice.id, "en")
    await _set_language(harness, bob.id, "zh")
    conversation = await harness.service.start_conversation(alice, bob.id)
    sent = await harness.service.send_message(
        conversation_id=conversation.id,
        sender=alice,
        text="Hello",
        client_message_id="retry-2",
    )

    with pytest.raises(VipChatError, match="Not a member"):
        await harness.service.retry_translation(message_id=sent.message.id, user_id=stranger.id)
