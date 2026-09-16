"""
Unit tests for Ditsala Meet Phase 1 (docs/DITSALA_MEET_SPEC.md §9) — real
Postgres, and the *real* `LiveKitRoomProvider` (not a stub): minting a
token is a local JWT-signing operation, so exercising it for real here
needs nothing more than throwaway key/secret strings — see
`domain/meetings/interfaces.py`'s docstring.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.domain.meetings.interfaces import RecordingHandle
from app.domain.meetings.service import MeetingError, MeetingService
from app.models.accounts import User
from app.repositories.meetings import (
    BreakoutRoomParticipantRepository,
    BreakoutRoomRepository,
    MeetingMessageRepository,
    MeetingParticipantRepository,
    MeetingPollRepository,
    MeetingPollVoteRepository,
    MeetingQuestionRepository,
    MeetingRecordingRepository,
    MeetingRepository,
)
from app.repositories.users import UserRepository
from app.services.meet.livekit import LiveKitRoomProvider

TEST_LIVEKIT_KEY = "test-key-0123456789"
TEST_LIVEKIT_SECRET = "test-secret-0123456789-0123456789"


@dataclass
class Harness:
    service: MeetingService
    users: UserRepository
    participants: MeetingParticipantRepository


class StubRoomProvider(LiveKitRoomProvider):
    """
    §9 Phase 2 host-control/recording/reaction methods all make real HTTP
    calls to LiveKit's own server API — there's no LiveKit server running
    in this dev environment (no Docker), so this stub subclasses the real
    adapter (keeping its real, network-free `create_access_token`) and
    only replaces the network-calling methods, recording calls for
    assertions. Same "adapter unverified against a live vendor" class of
    gap as `StitchPaymentProvider` — tracked in docs/SECURITY_GAPS.md.
    """

    def __init__(self) -> None:
        super().__init__(
            api_key=TEST_LIVEKIT_KEY, api_secret=TEST_LIVEKIT_SECRET, livekit_url="wss://test"
        )
        self.removed: list[str] = []
        self.publish_updates: list[tuple[str, bool]] = []
        self.broadcasts: list[tuple[str, bytes, str]] = []
        self.recordings_started: list[str] = []
        self.recordings_stopped: list[str] = []
        self.next_stop_status = "ready"

    async def remove_participant(self, *, room_name: str, participant_identity: str) -> None:
        self.removed.append(participant_identity)

    async def set_participant_can_publish(
        self, *, room_name: str, participant_identity: str, can_publish: bool
    ) -> None:
        self.publish_updates.append((participant_identity, can_publish))

    async def broadcast_data(self, *, room_name: str, payload: bytes, topic: str) -> None:
        self.broadcasts.append((room_name, payload, topic))

    async def start_recording(self, *, room_name: str, s3_key: str) -> RecordingHandle:
        self.recordings_started.append(s3_key)
        return RecordingHandle(egress_id=f"EG_{uuid.uuid4().hex}", status="processing")

    async def stop_recording(self, *, egress_id: str) -> RecordingHandle:
        self.recordings_stopped.append(egress_id)
        return RecordingHandle(
            egress_id=egress_id, status=self.next_stop_status, duration_seconds=42
        )


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
        await s.rollback()
    await engine.dispose()


@pytest.fixture
def room_provider() -> StubRoomProvider:
    return StubRoomProvider()


@pytest.fixture
def harness(session: AsyncSession, room_provider: StubRoomProvider) -> Harness:
    participants = MeetingParticipantRepository(session)
    service = MeetingService(
        meetings=MeetingRepository(session),
        participants=participants,
        room_provider=room_provider,
        recordings=MeetingRecordingRepository(session),
        messages=MeetingMessageRepository(session),
        polls=MeetingPollRepository(session),
        poll_votes=MeetingPollVoteRepository(session),
        questions=MeetingQuestionRepository(session),
        breakout_rooms=BreakoutRoomRepository(session),
        breakout_room_participants=BreakoutRoomParticipantRepository(session),
    )
    return Harness(service=service, users=UserRepository(session), participants=participants)


async def _make_user(harness: Harness, **overrides: object) -> User:
    fields: dict[str, object] = {
        "email": f"{uuid.uuid4()}@example.com",
        "phone": f"+27{uuid.uuid4().int % 10**9}",
        "display_name": "Meet Test User",
        "date_of_birth": datetime(1990, 1, 1),
        "national_id_hash": uuid.uuid4().hex,
        "account_state": "active",
        **overrides,
    }
    return await harness.users.add(User(**fields))


async def test_create_meeting_adds_host_as_participant(harness: Harness) -> None:
    host = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Sprint planning")

    assert meeting.status == "scheduled"
    assert meeting.livekit_room_name.startswith("meet-")

    participant = await harness.participants.get_by_meeting_and_user(meeting.id, host.id)
    assert participant is not None
    assert participant.role == "host"


async def test_join_issues_a_real_livekit_token_and_marks_meeting_live(
    harness: Harness,
) -> None:
    host = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Standup")

    result = await harness.service.join(meeting_id=meeting.id, user=host)

    assert result.meeting.status == "live"
    assert result.meeting.actual_start_at is not None
    assert result.participant.role == "host"
    assert result.access_token is not None
    assert result.access_token.token  # a real, non-empty signed JWT
    assert result.access_token.livekit_url == "wss://test"


async def test_second_participant_joins_with_participant_role(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="1:1")

    result = await harness.service.join(meeting_id=meeting.id, user=other)

    assert result.participant.role == "participant"


async def test_join_rejects_wrong_password(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Private", password="s3cret!")

    with pytest.raises(MeetingError, match="Incorrect meeting password"):
        await harness.service.join(meeting_id=meeting.id, user=other, password="wrong")


async def test_join_accepts_correct_password(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Private", password="s3cret!")

    result = await harness.service.join(meeting_id=meeting.id, user=other, password="s3cret!")
    assert result.access_token is not None
    assert result.access_token.token


async def test_join_rejects_locked_meeting(harness: Harness, session: AsyncSession) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Locked")
    meeting.locked_at = datetime.now(UTC)

    with pytest.raises(MeetingError, match="locked"):
        await harness.service.join(meeting_id=meeting.id, user=other)


async def test_guest_join_creates_a_participant_with_no_user_id(harness: Harness) -> None:
    host = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Open house")

    result = await harness.service.guest_join(meeting_id=meeting.id, guest_display_name="Guest")

    assert result.participant.user_id is None
    assert result.participant.guest_display_name == "Guest"
    assert result.access_token is not None
    assert result.access_token.token


async def test_end_meeting_requires_host(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Retro")

    with pytest.raises(MeetingError, match="Only the host"):
        await harness.service.end_meeting(meeting_id=meeting.id, acting_user_id=other.id)

    ended = await harness.service.end_meeting(meeting_id=meeting.id, acting_user_id=host.id)
    assert ended.status == "ended"
    assert ended.actual_end_at is not None


async def test_join_rejects_ended_meeting(harness: Harness) -> None:
    host = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Done")
    await harness.service.end_meeting(meeting_id=meeting.id, acting_user_id=host.id)

    with pytest.raises(MeetingError, match="ended"):
        await harness.service.join(meeting_id=meeting.id, user=host)


async def test_get_meeting_raises_for_unknown_id(harness: Harness) -> None:
    with pytest.raises(MeetingError, match="No such meeting"):
        await harness.service.get_meeting(uuid.uuid4())


# ---- Phase 2: waiting room --------------------------------------------------


async def test_join_with_waiting_room_enabled_holds_a_non_host_participant(
    harness: Harness,
) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(
        host=host, title="Gated", waiting_room_enabled=True
    )

    result = await harness.service.join(meeting_id=meeting.id, user=other)

    assert result.participant.admission_status == "waiting"
    assert result.access_token is None

    waiting = await harness.service.list_waiting_participants(
        meeting_id=meeting.id, acting_user_id=host.id
    )
    assert [p.id for p in waiting] == [result.participant.id]


async def test_admit_participant_lets_them_get_a_real_token_on_next_join(
    harness: Harness,
) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(
        host=host, title="Gated", waiting_room_enabled=True
    )
    waiting_result = await harness.service.join(meeting_id=meeting.id, user=other)

    await harness.service.admit_participant(
        meeting_id=meeting.id,
        acting_user_id=host.id,
        participant_id=waiting_result.participant.id,
    )
    admitted_result = await harness.service.join(meeting_id=meeting.id, user=other)

    assert admitted_result.participant.admission_status == "admitted"
    assert admitted_result.access_token is not None


async def test_non_host_cannot_admit_or_list_waiting_participants(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(
        host=host, title="Gated", waiting_room_enabled=True
    )
    waiting_result = await harness.service.join(meeting_id=meeting.id, user=other)

    with pytest.raises(MeetingError, match="host or a co-host"):
        await harness.service.list_waiting_participants(
            meeting_id=meeting.id, acting_user_id=other.id
        )
    with pytest.raises(MeetingError, match="host or a co-host"):
        await harness.service.admit_participant(
            meeting_id=meeting.id,
            acting_user_id=other.id,
            participant_id=waiting_result.participant.id,
        )


# ---- Phase 2: host / co-host controls ---------------------------------------


async def test_remove_participant_marks_removed_and_calls_room_provider(
    harness: Harness, room_provider: StubRoomProvider
) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Standup")
    result = await harness.service.join(meeting_id=meeting.id, user=other)

    await harness.service.remove_participant(
        meeting_id=meeting.id, acting_user_id=host.id, participant_id=result.participant.id
    )

    assert result.participant.admission_status == "removed"
    assert result.participant.left_at is not None
    assert room_provider.removed == [str(other.id)]

    with pytest.raises(MeetingError, match="removed"):
        await harness.service.join(meeting_id=meeting.id, user=other)


async def test_cannot_remove_the_host(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Standup")
    other_result = await harness.service.join(meeting_id=meeting.id, user=other)
    await harness.service.promote_co_host(
        meeting_id=meeting.id, acting_user_id=host.id, participant_id=other_result.participant.id
    )
    host_participant = await harness.participants.get_by_meeting_and_user(meeting.id, host.id)
    assert host_participant is not None

    with pytest.raises(MeetingError, match="Cannot remove the host"):
        await harness.service.remove_participant(
            meeting_id=meeting.id, acting_user_id=other.id, participant_id=host_participant.id
        )


async def test_promote_co_host_only_by_host(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    third = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Standup")
    result = await harness.service.join(meeting_id=meeting.id, user=other)
    await harness.service.join(meeting_id=meeting.id, user=third)

    promoted = await harness.service.promote_co_host(
        meeting_id=meeting.id, acting_user_id=host.id, participant_id=result.participant.id
    )
    assert promoted.role == "co_host"

    third_participant = await harness.participants.get_by_meeting_and_user(meeting.id, third.id)
    assert third_participant is not None
    with pytest.raises(MeetingError, match="Only the host"):
        await harness.service.promote_co_host(
            meeting_id=meeting.id,
            acting_user_id=other.id,
            participant_id=third_participant.id,
        )


async def test_mute_participant_calls_room_provider_with_can_publish_false(
    harness: Harness, room_provider: StubRoomProvider
) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Standup")
    result = await harness.service.join(meeting_id=meeting.id, user=other)

    await harness.service.set_participant_muted(
        meeting_id=meeting.id,
        acting_user_id=host.id,
        participant_id=result.participant.id,
        muted=True,
    )

    assert room_provider.publish_updates == [(str(other.id), False)]


async def test_lock_meeting_only_by_host_and_blocks_join(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Standup")

    with pytest.raises(MeetingError, match="Only the host"):
        await harness.service.set_locked(
            meeting_id=meeting.id, acting_user_id=other.id, locked=True
        )

    locked = await harness.service.set_locked(
        meeting_id=meeting.id, acting_user_id=host.id, locked=True
    )
    assert locked.locked_at is not None
    with pytest.raises(MeetingError, match="locked"):
        await harness.service.join(meeting_id=meeting.id, user=other)

    unlocked = await harness.service.set_locked(
        meeting_id=meeting.id, acting_user_id=host.id, locked=False
    )
    assert unlocked.locked_at is None


# ---- Phase 2: reactions / raise-hand -----------------------------------------


async def test_send_reaction_and_raise_hand_broadcast_via_room_provider(
    harness: Harness, room_provider: StubRoomProvider
) -> None:
    host = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Standup")
    host_participant = await harness.participants.get_by_meeting_and_user(meeting.id, host.id)
    assert host_participant is not None

    await harness.service.send_reaction(
        meeting_id=meeting.id, participant=host_participant, reaction="👍"
    )
    await harness.service.set_hand_raised(
        meeting_id=meeting.id, participant=host_participant, raised=True
    )

    topics = [topic for (_room, _payload, topic) in room_provider.broadcasts]
    assert topics == ["reaction", "hand_raise"]


# ---- Phase 2: recording -------------------------------------------------------


async def test_start_and_stop_recording(harness: Harness, room_provider: StubRoomProvider) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Standup")

    with pytest.raises(MeetingError, match="host or a co-host"):
        await harness.service.start_recording(meeting_id=meeting.id, acting_user_id=other.id)

    recording = await harness.service.start_recording(meeting_id=meeting.id, acting_user_id=host.id)
    assert recording.status == "processing"
    assert room_provider.recordings_started == [recording.storage_key]

    room_provider.next_stop_status = "ready"
    stopped = await harness.service.stop_recording(
        meeting_id=meeting.id, acting_user_id=host.id, recording_id=recording.id
    )
    assert stopped.status == "ready"
    assert stopped.duration_seconds == 42
    assert stopped.ended_at is not None

    recordings = await harness.service.list_recordings(
        meeting_id=meeting.id, acting_user_id=host.id
    )
    assert [r.id for r in recordings] == [recording.id]


# ---- Phase 2: chat -------------------------------------------------------------


async def test_send_message_broadcast_and_private_visibility(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    third = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Standup")
    host_p = await harness.participants.get_by_meeting_and_user(meeting.id, host.id)
    other_result = await harness.service.join(meeting_id=meeting.id, user=other)
    third_result = await harness.service.join(meeting_id=meeting.id, user=third)
    assert host_p is not None

    await harness.service.send_message(meeting_id=meeting.id, sender=host_p, body="Hello everyone")
    await harness.service.send_message(
        meeting_id=meeting.id,
        sender=host_p,
        body="Just for you",
        recipient_participant_id=other_result.participant.id,
    )

    other_messages = await harness.service.list_messages(
        meeting_id=meeting.id, participant_id=other_result.participant.id
    )
    third_messages = await harness.service.list_messages(
        meeting_id=meeting.id, participant_id=third_result.participant.id
    )
    assert [m.body for m in other_messages] == ["Hello everyone", "Just for you"]
    assert [m.body for m in third_messages] == ["Hello everyone"]


# ---- Phase 2: polls -------------------------------------------------------------


async def test_poll_lifecycle(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Standup")
    host_p = await harness.participants.get_by_meeting_and_user(meeting.id, host.id)
    other_result = await harness.service.join(meeting_id=meeting.id, user=other)
    assert host_p is not None

    poll = await harness.service.create_poll(
        meeting_id=meeting.id,
        acting_user_id=host.id,
        creator=host_p,
        question="Best time?",
        options=["9am", "2pm"],
    )
    await harness.service.vote_poll(poll_id=poll.id, voter=host_p, option_index=0)
    await harness.service.vote_poll(
        poll_id=poll.id, voter=other_result.participant, option_index=0
    )
    # re-voting changes the existing vote rather than adding a second one
    await harness.service.vote_poll(poll_id=poll.id, voter=host_p, option_index=1)

    results = await harness.service.get_poll_results(poll_id=poll.id)
    assert results.counts == {0: 1, 1: 1}

    closed = await harness.service.close_poll(
        meeting_id=meeting.id, acting_user_id=host.id, poll_id=poll.id
    )
    assert closed.closed_at is not None
    with pytest.raises(MeetingError, match="closed"):
        await harness.service.vote_poll(poll_id=poll.id, voter=host_p, option_index=0)


async def test_only_host_or_cohost_can_create_a_poll(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Standup")
    other_result = await harness.service.join(meeting_id=meeting.id, user=other)

    with pytest.raises(MeetingError, match="host or a co-host"):
        await harness.service.create_poll(
            meeting_id=meeting.id,
            acting_user_id=other.id,
            creator=other_result.participant,
            question="?",
            options=["a", "b"],
        )


# ---- Phase 2: Q&A ----------------------------------------------------------------


async def test_question_lifecycle(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Town hall")
    other_result = await harness.service.join(meeting_id=meeting.id, user=other)

    question = await harness.service.ask_question(
        meeting_id=meeting.id, asker=other_result.participant, body="What's the roadmap?"
    )
    assert question.status == "open"

    upvoted = await harness.service.upvote_question(question_id=question.id)
    assert upvoted.upvote_count == 1

    answered = await harness.service.answer_question(
        meeting_id=meeting.id, acting_user_id=host.id, question_id=question.id
    )
    assert answered.status == "answered"
    assert answered.answered_at is not None

    questions = await harness.service.list_questions(meeting_id=meeting.id)
    assert [q.id for q in questions] == [question.id]


async def test_only_host_or_cohost_can_answer_or_dismiss_a_question(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Town hall")
    other_result = await harness.service.join(meeting_id=meeting.id, user=other)
    question = await harness.service.ask_question(
        meeting_id=meeting.id, asker=other_result.participant, body="?"
    )

    with pytest.raises(MeetingError, match="host or a co-host"):
        await harness.service.answer_question(
            meeting_id=meeting.id, acting_user_id=other.id, question_id=question.id
        )
    with pytest.raises(MeetingError, match="host or a co-host"):
        await harness.service.dismiss_question(
            meeting_id=meeting.id, acting_user_id=other.id, question_id=question.id
        )


# ---- Phase 2: breakout rooms ------------------------------------------------


async def test_breakout_room_lifecycle(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Workshop")
    other_result = await harness.service.join(meeting_id=meeting.id, user=other)

    rooms = await harness.service.create_breakout_rooms(
        meeting_id=meeting.id, acting_user_id=host.id, names=["Group A", "Group B"]
    )
    assert [r.name for r in rooms] == ["Group A", "Group B"]
    assert rooms[0].livekit_room_name != rooms[1].livekit_room_name

    await harness.service.assign_to_breakout_room(
        meeting_id=meeting.id,
        acting_user_id=host.id,
        breakout_room_id=rooms[0].id,
        participant_id=other_result.participant.id,
    )

    token = await harness.service.join_breakout_room(
        meeting_id=meeting.id,
        breakout_room_id=rooms[0].id,
        participant=other_result.participant,
    )
    assert token.token

    unassigned_participant = other_result.participant
    with pytest.raises(MeetingError, match="not been assigned"):
        await harness.service.join_breakout_room(
            meeting_id=meeting.id,
            breakout_room_id=rooms[1].id,
            participant=unassigned_participant,
        )

    closed = await harness.service.close_breakout_rooms(
        meeting_id=meeting.id, acting_user_id=host.id
    )
    assert all(r.closed_at is not None for r in closed)

    with pytest.raises(MeetingError, match="closed"):
        await harness.service.join_breakout_room(
            meeting_id=meeting.id,
            breakout_room_id=rooms[0].id,
            participant=other_result.participant,
        )


async def test_only_host_or_cohost_can_create_or_close_breakout_rooms(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Workshop")
    await harness.service.join(meeting_id=meeting.id, user=other)

    with pytest.raises(MeetingError, match="host or a co-host"):
        await harness.service.create_breakout_rooms(
            meeting_id=meeting.id, acting_user_id=other.id, names=["Group A"]
        )
    with pytest.raises(MeetingError, match="host or a co-host"):
        await harness.service.close_breakout_rooms(meeting_id=meeting.id, acting_user_id=other.id)
