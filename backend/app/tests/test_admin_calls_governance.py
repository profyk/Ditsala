"""
Unit tests for `AdminCallGovernanceService` — real Postgres, real
`CallService` underneath (delegated to for the actual end mutation).
Same shape as test_admin_meetings_governance.py: admin visibility into
calls platform-wide, and admin override of a call that isn't theirs.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.domain.admin.calls_governance import AdminCallGovernanceService, CallGovernanceError
from app.domain.calls.service import CallService
from app.models.accounts import User
from app.models.devices import Device
from app.models.messaging import Conversation, ConversationMember
from app.repositories.admin import AuditLogRepository
from app.repositories.calls import CallParticipantRepository, CallRepository
from app.repositories.conversations import ConversationMemberRepository, ConversationRepository
from app.repositories.devices import DeviceRepository
from app.repositories.users import UserRepository
from app.services.realtime.websocket_manager import ConnectionManager


@dataclass
class Harness:
    governance: AdminCallGovernanceService
    calls_service: CallService
    users: UserRepository
    devices: DeviceRepository
    conversations: ConversationRepository
    conversation_members: ConversationMemberRepository
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
    conversations = ConversationRepository(session)
    conversation_members = ConversationMemberRepository(session)
    calls_repo = CallRepository(session)
    calls_service = CallService(
        calls=calls_repo,
        participants=CallParticipantRepository(session),
        conversations=conversations,
        conversation_members=conversation_members,
        devices=devices,
        connection_manager=ConnectionManager(),
    )
    audit_log = AuditLogRepository(session)
    governance = AdminCallGovernanceService(
        calls=calls_repo, call_service=calls_service, audit_log=audit_log
    )
    return Harness(
        governance=governance,
        calls_service=calls_service,
        users=users,
        devices=devices,
        conversations=conversations,
        conversation_members=conversation_members,
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


async def test_list_live_spans_every_participant_pair(harness: Harness) -> None:
    alice, _d1 = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)
    carol, _d3 = await _make_user_with_device(harness)
    dave, _d4 = await _make_user_with_device(harness)
    conversation_ab = await _make_direct_conversation(harness, alice.id, bob.id)
    conversation_cd = await _make_direct_conversation(harness, carol.id, dave.id)

    call_ab = await harness.calls_service.initiate_call(
        initiator_id=alice.id, conversation_id=conversation_ab.id, call_type="voice"
    )
    call_cd = await harness.calls_service.initiate_call(
        initiator_id=carol.id, conversation_id=conversation_cd.id, call_type="video"
    )

    live = await harness.governance.list_live()
    ids = {c.id for c in live}
    assert call_ab.id in ids
    assert call_cd.id in ids


async def test_admin_can_end_a_call_that_is_not_theirs(harness: Harness) -> None:
    alice, _d1 = await _make_user_with_device(harness)
    bob, _d2 = await _make_user_with_device(harness)
    conversation = await _make_direct_conversation(harness, alice.id, bob.id)
    call = await harness.calls_service.initiate_call(
        initiator_id=alice.id, conversation_id=conversation.id, call_type="voice"
    )
    await harness.calls_service.answer_call(call_id=call.id, user_id=bob.id)

    admin_id = uuid.uuid4()
    ended = await harness.governance.end_call(
        admin_id=admin_id, call_id=call.id, reason="policy violation reported"
    )
    assert ended.status == "ended"

    entries = await harness.audit_log.list_for_target("call", call.id)
    assert any(e.action == "admin.call.ended" for e in entries)
    entry = next(e for e in entries if e.action == "admin.call.ended")
    assert entry.metadata_json == {"reason": "policy violation reported"}
    assert entry.actor_id == admin_id


async def test_end_call_rejects_unknown_call(harness: Harness) -> None:
    with pytest.raises(CallGovernanceError, match="No such call"):
        await harness.governance.end_call(
            admin_id=uuid.uuid4(), call_id=uuid.uuid4(), reason="test"
        )


async def test_get_call_rejects_unknown_call(harness: Harness) -> None:
    with pytest.raises(CallGovernanceError, match="No such call"):
        await harness.governance.get_call(uuid.uuid4())
