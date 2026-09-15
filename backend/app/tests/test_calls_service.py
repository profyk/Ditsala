"""
Unit tests for WebRTC call signaling (§27) — real Postgres. The real
`ConnectionManager` is used as-is: with no live WebSocket connections
registered, broadcasting is a safe no-op — this still proves the service
resolves the right devices and sends the right event shape.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.domain.calls.service import CallError, CallService
from app.models.accounts import User
from app.models.devices import Device
from app.models.messaging import Conversation, ConversationMember
from app.repositories.calls import CallParticipantRepository, CallRepository
from app.repositories.conversations import ConversationMemberRepository, ConversationRepository
from app.repositories.devices import DeviceRepository
from app.repositories.users import UserRepository
from app.services.realtime.websocket_manager import ConnectionManager


@dataclass
class Harness:
    service: CallService
    users: UserRepository
    devices: DeviceRepository
    conversations: ConversationRepository
    conversation_members: ConversationMemberRepository


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
    conversations = ConversationRepository(session)
    conversation_members = ConversationMemberRepository(session)
    service = CallService(
        calls=CallRepository(session),
        participants=CallParticipantRepository(session),
        conversations=conversations,
        conversation_members=conversation_members,
        devices=devices,
        connection_manager=ConnectionManager(),
    )
    return Harness(
        service=service, users=users, devices=devices,
        conversations=conversations, conversation_members=conversation_members,
    )


async def _make_user_with_device(harness: Harness) -> tuple[User, Device]:
    user = await harness.users.add(
        User(
            email=f"{uuid.uuid4()}@example.com",
            phone=f"+27{uuid.uuid4().int % 10**9}",
            display_name="Calls Test User",
            date_of_birth=datetime(1990, 1, 1),
            national_id_hash=uuid.uuid4().hex,
            account_state="active",
        )
    )
    now = datetime.now(UTC)
    device = await harness.devices.add(
        Device(
            user_id=user.id, device_name="Test Device", platform="ios",
            first_seen_at=now, last_seen_at=now, is_trusted=True,
        )
    )
    return user, device


async def _make_direct_conversation(
    harness: Harness, alice_id: uuid.UUID, bob_id: uuid.UUID
) -> Conversation:
    conversation = await harness.conversations.add(Conversation(type="direct", created_by=alice_id))
    now = datetime.now(UTC)
    for uid in (alice_id, bob_id):
        await harness.conversation_members.add(
            ConversationMember(conversation_id=conversation.id, user_id=uid, joined_at=now)
        )
    return conversation


async def test_initiate_call_requires_direct_conversation(harness: Harness) -> None:
    alice, _d1 = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)
    carol, _d3 = await _make_user_with_device(harness)
    group = await harness.conversations.add(Conversation(type="group", created_by=alice.id))
    now = datetime.now(UTC)
    for uid in (alice.id, bob.id, carol.id):
        await harness.conversation_members.add(
            ConversationMember(conversation_id=group.id, user_id=uid, joined_at=now)
        )

    with pytest.raises(CallError, match="Only 1:1 calls"):
        await harness.service.initiate_call(
            initiator_id=alice.id, conversation_id=group.id, call_type="voice"
        )


async def test_initiate_call_requires_membership(harness: Harness) -> None:
    alice, _d1 = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)
    outsider, _d3 = await _make_user_with_device(harness)
    conversation = await _make_direct_conversation(harness, alice.id, bob.id)

    with pytest.raises(CallError, match="Not a member"):
        await harness.service.initiate_call(
            initiator_id=outsider.id, conversation_id=conversation.id, call_type="voice"
        )


async def test_full_call_lifecycle_voice_to_video_switch(harness: Harness) -> None:
    alice, _d1 = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)
    conversation = await _make_direct_conversation(harness, alice.id, bob.id)

    call = await harness.service.initiate_call(
        initiator_id=alice.id, conversation_id=conversation.id, call_type="voice"
    )
    assert call.status == "ringing"
    assert call.type == "voice"

    answered = await harness.service.answer_call(call_id=call.id, user_id=bob.id)
    assert answered.status == "active"
    assert answered.started_at is not None

    # Either side can switch voice <-> video at any point during an active call.
    switched = await harness.service.switch_media(
        call_id=call.id, user_id=bob.id, call_type="video"
    )
    assert switched.type == "video"

    switched_back = await harness.service.switch_media(
        call_id=call.id, user_id=alice.id, call_type="voice"
    )
    assert switched_back.type == "voice"

    ended = await harness.service.end_call(call_id=call.id, user_id=alice.id)
    assert ended.status == "ended"
    assert ended.ended_at is not None

    # Ending twice is a no-op, not an error.
    ended_again = await harness.service.end_call(call_id=call.id, user_id=alice.id)
    assert ended_again.status == "ended"


async def test_cannot_switch_media_before_call_is_active(harness: Harness) -> None:
    alice, _d1 = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)
    conversation = await _make_direct_conversation(harness, alice.id, bob.id)
    call = await harness.service.initiate_call(
        initiator_id=alice.id, conversation_id=conversation.id, call_type="voice"
    )

    with pytest.raises(CallError, match="active call"):
        await harness.service.switch_media(call_id=call.id, user_id=alice.id, call_type="video")


async def test_decline_call(harness: Harness) -> None:
    alice, _d1 = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)
    conversation = await _make_direct_conversation(harness, alice.id, bob.id)
    call = await harness.service.initiate_call(
        initiator_id=alice.id, conversation_id=conversation.id, call_type="video"
    )

    declined = await harness.service.decline_call(call_id=call.id, user_id=bob.id)
    assert declined.status == "declined"
    assert declined.ended_at is not None

    with pytest.raises(CallError, match="Cannot decline"):
        await harness.service.decline_call(call_id=call.id, user_id=bob.id)


async def test_ending_a_ringing_call_marks_it_missed(harness: Harness) -> None:
    alice, _d1 = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)
    conversation = await _make_direct_conversation(harness, alice.id, bob.id)
    call = await harness.service.initiate_call(
        initiator_id=alice.id, conversation_id=conversation.id, call_type="voice"
    )

    ended = await harness.service.end_call(call_id=call.id, user_id=alice.id)
    assert ended.status == "missed"


async def test_relay_signal_is_a_noop_after_call_ends(harness: Harness) -> None:
    alice, _d1 = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)
    conversation = await _make_direct_conversation(harness, alice.id, bob.id)
    call = await harness.service.initiate_call(
        initiator_id=alice.id, conversation_id=conversation.id, call_type="voice"
    )
    await harness.service.decline_call(call_id=call.id, user_id=bob.id)

    # Shouldn't raise — a stale signal for an ended call is dropped silently.
    await harness.service.relay_signal(
        call_id=call.id, from_user_id=alice.id, payload={"kind": "ice-candidate"}
    )


async def test_relay_signal_requires_participant(harness: Harness) -> None:
    alice, _d1 = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)
    outsider, _d3 = await _make_user_with_device(harness)
    conversation = await _make_direct_conversation(harness, alice.id, bob.id)
    call = await harness.service.initiate_call(
        initiator_id=alice.id, conversation_id=conversation.id, call_type="voice"
    )

    with pytest.raises(CallError, match="Not a participant"):
        await harness.service.relay_signal(
            call_id=call.id, from_user_id=outsider.id, payload={"kind": "offer"}
        )


async def test_list_calls_for_user(harness: Harness) -> None:
    alice, _d1 = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)
    conversation = await _make_direct_conversation(harness, alice.id, bob.id)
    call = await harness.service.initiate_call(
        initiator_id=alice.id, conversation_id=conversation.id, call_type="voice"
    )

    assert [c.id for c in await harness.service.list_calls(alice.id)] == [call.id]
    assert [c.id for c in await harness.service.list_calls(bob.id)] == [call.id]
