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
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.domain.meetings.interfaces import RecordingHandle
from app.domain.meetings.service import (
    MeetingError,
    MeetingService,
    get_live_deadline,
    get_room_phase,
)
from app.domain.messaging.interfaces import StorageProvider
from app.domain.translation.service import TranslationService
from app.models.accounts import User
from app.repositories.admin import SystemConfigRepository
from app.repositories.meetings import (
    BreakoutRoomParticipantRepository,
    BreakoutRoomRepository,
    MeetingDocumentRepository,
    MeetingMessageRepository,
    MeetingParticipantRepository,
    MeetingPollRepository,
    MeetingPollVoteRepository,
    MeetingQuestionRepository,
    MeetingRecordingRepository,
    MeetingRegistrationRepository,
    MeetingRepository,
)
from app.repositories.translation import (
    ConferenceLanguagePreferenceRepository,
    InterpreterSessionRepository,
    TranslationRequestRepository,
    TranslationUsageRepository,
    UserLanguagePreferenceRepository,
)
from app.repositories.users import UserRepository
from app.services.meet.livekit import LiveKitRoomProvider
from app.services.translation.mock import MockTranslationProvider

TEST_LIVEKIT_KEY = "test-key-0123456789"
TEST_LIVEKIT_SECRET = "test-secret-0123456789-0123456789"


class StubStorageProvider(StorageProvider):
    async def create_upload_url(self, *, key: str, content_type: str) -> str:
        return f"https://stub-upload.test/{key}"

    async def create_download_url(self, *, key: str) -> str:
        return f"https://stub-download.test/{key}"

    async def put_object(self, *, key: str, data: bytes, content_type: str) -> None:
        pass


@dataclass
class Harness:
    service: MeetingService
    users: UserRepository
    participants: MeetingParticipantRepository
    conference_language_preferences: ConferenceLanguagePreferenceRepository


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
    conference_language_preferences = ConferenceLanguagePreferenceRepository(session)
    translation_service = TranslationService(
        translation_requests=TranslationRequestRepository(session),
        translation_usage=TranslationUsageRepository(session),
        user_language_preferences=UserLanguagePreferenceRepository(session),
        interpreter_sessions=InterpreterSessionRepository(session),
        system_config=SystemConfigRepository(session),
        provider=MockTranslationProvider(),
    )
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
        registrations=MeetingRegistrationRepository(session),
        documents=MeetingDocumentRepository(session),
        storage_provider=StubStorageProvider(),
        conference_language_preferences=conference_language_preferences,
        translation_service=translation_service,
        users=UserRepository(session),
    )
    return Harness(
        service=service,
        users=UserRepository(session),
        participants=participants,
        conference_language_preferences=conference_language_preferences,
    )


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


async def test_create_meeting_generates_a_six_digit_host_pin(harness: Harness) -> None:
    host = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Standup")

    pin = meeting.host_pin  # type: ignore[attr-defined]
    assert isinstance(pin, str)
    assert len(pin) == 6
    assert pin.isdigit()
    # Only the hash is actually persisted — never the plaintext.
    assert meeting.host_pin_hash is not None
    assert meeting.host_pin_hash != pin


async def test_host_pin_join_authenticates_as_the_host(harness: Harness) -> None:
    """The whole point: a same-origin, same-tab alternative to the
    mobile app's host-link handoff — no token, no navigation, just the
    PIN a real client would read off the "meeting scheduled" screen."""
    host = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Standup")
    pin = meeting.host_pin  # type: ignore[attr-defined]

    result = await harness.service.host_pin_join(meeting_id=meeting.id, pin=pin)
    assert result.participant.role == "host"
    assert result.participant.user_id == host.id
    assert result.access_token is not None


async def test_host_pin_join_rejects_wrong_pin(harness: Harness) -> None:
    host = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Standup")

    with pytest.raises(MeetingError, match="Incorrect host PIN"):
        await harness.service.host_pin_join(meeting_id=meeting.id, pin="000000")


async def test_host_pin_join_bypasses_the_meeting_password(harness: Harness) -> None:
    """A host (or co-host) using the PIN never needs the separate guest
    password — same bypass `join()`'s own is_host check already gives
    an authenticated host calling POST /join directly."""
    host = await _make_user(harness)
    meeting = await harness.service.create_meeting(
        host=host, title="Private", password="guest-secret"
    )
    pin = meeting.host_pin  # type: ignore[attr-defined]

    result = await harness.service.host_pin_join(meeting_id=meeting.id, pin=pin)
    assert result.access_token is not None


async def test_list_hosted_meetings_returns_only_this_hosts_meetings(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    mine = await harness.service.create_meeting(host=host, title="Mine")
    await harness.service.create_meeting(host=other, title="Not mine")

    meetings = await harness.service.list_hosted_meetings(host.id)

    assert [m.id for m in meetings] == [mine.id]


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


async def test_get_participant_status_lets_a_guest_poll_without_a_new_row_each_time(
    harness: Harness,
) -> None:
    host = await _make_user(harness)
    meeting = await harness.service.create_meeting(
        host=host, title="Gated", waiting_room_enabled=True
    )
    waiting_result = await harness.service.guest_join(
        meeting_id=meeting.id, guest_display_name="Guest"
    )
    assert waiting_result.access_token is None

    still_waiting = await harness.service.get_participant_status(
        meeting_id=meeting.id, participant_id=waiting_result.participant.id
    )
    assert still_waiting.access_token is None
    assert still_waiting.participant.id == waiting_result.participant.id

    await harness.service.admit_participant(
        meeting_id=meeting.id, acting_user_id=host.id, participant_id=waiting_result.participant.id
    )
    admitted = await harness.service.get_participant_status(
        meeting_id=meeting.id, participant_id=waiting_result.participant.id
    )
    assert admitted.access_token is not None


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


async def test_set_waiting_room_enabled_only_by_host_and_changes_next_join(
    harness: Harness,
) -> None:
    """The host's live "hold guests until admitted" vs "let them straight
    into the room" choice — previously only settable once, at creation."""
    host = await _make_user(harness)
    other = await _make_user(harness)
    # Created with waiting_room_enabled defaulting to False.
    meeting = await harness.service.create_meeting(host=host, title="Standup")

    with pytest.raises(MeetingError, match="Only the host"):
        await harness.service.set_waiting_room_enabled(
            meeting_id=meeting.id, acting_user_id=other.id, enabled=True
        )

    updated = await harness.service.set_waiting_room_enabled(
        meeting_id=meeting.id, acting_user_id=host.id, enabled=True
    )
    assert updated.waiting_room_enabled is True

    result = await harness.service.join(meeting_id=meeting.id, user=other)
    assert result.participant.admission_status == "waiting"
    assert result.access_token is None

    reverted = await harness.service.set_waiting_room_enabled(
        meeting_id=meeting.id, acting_user_id=host.id, enabled=False
    )
    assert reverted.waiting_room_enabled is False

    third = await _make_user(harness)
    result2 = await harness.service.join(meeting_id=meeting.id, user=third)
    assert result2.participant.admission_status == "admitted"
    assert result2.access_token is not None


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


# ---- multilingual chat (business-model kickoff §13/§18/§20) --------------------


async def test_set_and_get_participant_language(harness: Harness) -> None:
    host = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Global Standup")
    host_p = await harness.participants.get_by_meeting_and_user(meeting.id, host.id)
    assert host_p is not None

    assert await harness.service.get_participant_language(host_p.id) is None

    preference = await harness.service.set_participant_language(
        meeting_id=meeting.id, participant_id=host_p.id, language="fr"
    )
    assert preference.language == "fr"

    fetched = await harness.service.get_participant_language(host_p.id)
    assert fetched is not None and fetched.language == "fr"

    # Setting again updates the same row rather than creating a second one.
    await harness.service.set_participant_language(
        meeting_id=meeting.id, participant_id=host_p.id, language="zu"
    )
    languages = await harness.service.list_participant_languages(meeting.id)
    assert [p.language for p in languages] == ["zu"]


async def test_translate_message_uses_viewers_stored_language(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Global Standup")
    host_p = await harness.participants.get_by_meeting_and_user(meeting.id, host.id)
    other_result = await harness.service.join(meeting_id=meeting.id, user=other)
    assert host_p is not None

    message = await harness.service.send_message(
        meeting_id=meeting.id, sender=host_p, body="Hello, nice to meet you."
    )
    await harness.service.set_participant_language(
        meeting_id=meeting.id, participant_id=other_result.participant.id, language="zh"
    )

    translation = await harness.service.translate_message(
        meeting_id=meeting.id,
        message_id=message.id,
        viewer_participant_id=other_result.participant.id,
    )
    assert translation.translated_text == "你好，很高兴认识你。"
    assert translation.target_language == "zh"
    assert translation.status == "completed"


async def test_translate_message_requires_viewer_language_set(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Global Standup")
    host_p = await harness.participants.get_by_meeting_and_user(meeting.id, host.id)
    other_result = await harness.service.join(meeting_id=meeting.id, user=other)
    assert host_p is not None

    message = await harness.service.send_message(meeting_id=meeting.id, sender=host_p, body="Hi")
    with pytest.raises(MeetingError, match="Set your conference language"):
        await harness.service.translate_message(
            meeting_id=meeting.id,
            message_id=message.id,
            viewer_participant_id=other_result.participant.id,
        )


async def test_translate_message_rejects_message_from_another_meeting(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting_a = await harness.service.create_meeting(host=host, title="Meeting A")
    meeting_b = await harness.service.create_meeting(host=host, title="Meeting B")
    host_a = await harness.participants.get_by_meeting_and_user(meeting_a.id, host.id)
    other_result_b = await harness.service.join(meeting_id=meeting_b.id, user=other)
    assert host_a is not None

    message = await harness.service.send_message(meeting_id=meeting_a.id, sender=host_a, body="Hi")
    await harness.service.set_participant_language(
        meeting_id=meeting_b.id, participant_id=other_result_b.participant.id, language="zh"
    )
    with pytest.raises(MeetingError, match="No such message"):
        await harness.service.translate_message(
            meeting_id=meeting_b.id,
            message_id=message.id,
            viewer_participant_id=other_result_b.participant.id,
        )


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


# ---- Phase 4: webinar stage control ------------------------------------------


async def test_webinar_participants_default_to_audience_with_a_view_only_token(
    harness: Harness,
) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(
        host=host, title="All-hands", meeting_type="webinar"
    )

    host_result = await harness.service.join(meeting_id=meeting.id, user=host)
    other_result = await harness.service.join(meeting_id=meeting.id, user=other)

    assert host_result.participant.stage_status == "on_stage"
    assert other_result.participant.stage_status == "audience"

    assert other_result.access_token is not None
    claims = jwt.decode(
        other_result.access_token.token, options={"verify_signature": False}
    )
    assert claims["video"]["canPublish"] is False

    assert host_result.access_token is not None
    host_claims = jwt.decode(host_result.access_token.token, options={"verify_signature": False})
    assert host_claims["video"]["canPublish"] is True


async def test_standard_meetings_keep_everyone_on_stage(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Standup")

    other_result = await harness.service.join(meeting_id=meeting.id, user=other)
    assert other_result.participant.stage_status == "on_stage"


async def test_invite_to_stage_and_move_to_audience(
    harness: Harness, room_provider: StubRoomProvider
) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(
        host=host, title="Town hall", meeting_type="town_hall"
    )
    other_result = await harness.service.join(meeting_id=meeting.id, user=other)
    assert other_result.participant.stage_status == "audience"

    promoted = await harness.service.invite_to_stage(
        meeting_id=meeting.id, acting_user_id=host.id, participant_id=other_result.participant.id
    )
    assert promoted.stage_status == "on_stage"
    assert room_provider.publish_updates[-1] == (str(other.id), True)

    demoted = await harness.service.move_to_audience(
        meeting_id=meeting.id, acting_user_id=host.id, participant_id=other_result.participant.id
    )
    assert demoted.stage_status == "audience"
    assert room_provider.publish_updates[-1] == (str(other.id), False)


async def test_cannot_move_the_host_to_the_audience(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(
        host=host, title="Town hall", meeting_type="town_hall"
    )
    other_result = await harness.service.join(meeting_id=meeting.id, user=other)
    await harness.service.promote_co_host(
        meeting_id=meeting.id, acting_user_id=host.id, participant_id=other_result.participant.id
    )
    host_participant = await harness.participants.get_by_meeting_and_user(meeting.id, host.id)
    assert host_participant is not None

    with pytest.raises(MeetingError, match="Cannot move the host"):
        await harness.service.move_to_audience(
            meeting_id=meeting.id, acting_user_id=other.id, participant_id=host_participant.id
        )


# ---- Phase 4: webinar registration ---------------------------------------------


async def test_register_for_meeting_is_idempotent_by_email(harness: Harness) -> None:
    host = await _make_user(harness)
    meeting = await harness.service.create_meeting(
        host=host, title="Product launch", meeting_type="webinar"
    )

    first = await harness.service.register_for_meeting(
        meeting_id=meeting.id, email="fan@example.com", display_name="A Fan"
    )
    second = await harness.service.register_for_meeting(
        meeting_id=meeting.id, email="fan@example.com", display_name="A Fan (updated)"
    )

    assert first.id == second.id
    assert second.display_name == "A Fan (updated)"

    registrations = await harness.service.list_registrations(
        meeting_id=meeting.id, acting_user_id=host.id
    )
    assert [r.id for r in registrations] == [first.id]


async def test_only_host_or_cohost_can_list_registrations(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(
        host=host, title="Webinar", meeting_type="webinar"
    )
    await harness.service.join(meeting_id=meeting.id, user=other)

    with pytest.raises(MeetingError, match="host or a co-host"):
        await harness.service.list_registrations(meeting_id=meeting.id, acting_user_id=other.id)


async def test_joining_marks_a_matching_registration_as_attended(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness, email="registrant@example.com")
    meeting = await harness.service.create_meeting(
        host=host, title="Webinar", meeting_type="webinar"
    )
    registration = await harness.service.register_for_meeting(
        meeting_id=meeting.id, email="registrant@example.com", display_name="Registrant"
    )
    assert registration.attended_at is None

    await harness.service.join(meeting_id=meeting.id, user=other)

    registrations = await harness.service.list_registrations(
        meeting_id=meeting.id, acting_user_id=host.id
    )
    assert registrations[0].attended_at is not None


# ---- Phase 4: join-info and the scheduled-meeting early-join window -----------


async def test_join_info_reports_password_and_scheduling_state(harness: Harness) -> None:
    host = await _make_user(harness)
    meeting = await harness.service.create_meeting(
        host=host,
        title="Board meeting",
        password="s3cret!",
        scheduled_start_at=datetime.now(UTC) + timedelta(hours=2),
    )

    info = await harness.service.get_join_info(meeting.id)

    assert info.requires_password is True
    assert info.joinable_now is False
    assert info.meeting.scheduled_start_at is not None


async def test_non_host_cannot_join_a_meeting_far_before_its_scheduled_start(
    harness: Harness,
) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(
        host=host,
        title="Board meeting",
        scheduled_start_at=datetime.now(UTC) + timedelta(hours=2),
    )

    with pytest.raises(MeetingError, match="hasn't started yet"):
        await harness.service.join(meeting_id=meeting.id, user=other)

    # The host isn't subject to the early-join window — they need to be
    # able to start a scheduled meeting whenever they're ready.
    host_result = await harness.service.join(meeting_id=meeting.id, user=host)
    assert host_result.access_token is not None


async def test_join_is_allowed_within_the_early_join_window(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(
        host=host,
        title="Board meeting",
        scheduled_start_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    result = await harness.service.join(meeting_id=meeting.id, user=other)
    assert result.access_token is not None


# ---- Conference Room: prep/live phase, duration extension ------------------


async def test_room_phase_scheduled_before_prep_window(harness: Harness) -> None:
    host = await _make_user(harness)
    meeting = await harness.service.create_meeting(
        host=host,
        title="Board meeting",
        scheduled_start_at=datetime.now(UTC) + timedelta(hours=2),
        prep_lead_minutes=15,
    )
    assert get_room_phase(meeting) == "scheduled"


async def test_room_phase_prep_within_lead_window(harness: Harness) -> None:
    host = await _make_user(harness)
    meeting = await harness.service.create_meeting(
        host=host,
        title="Board meeting",
        scheduled_start_at=datetime.now(UTC) + timedelta(minutes=10),
        prep_lead_minutes=15,
    )
    assert get_room_phase(meeting) == "prep"


async def test_room_phase_live_once_someone_has_joined(harness: Harness) -> None:
    host = await _make_user(harness)
    meeting = await harness.service.create_meeting(
        host=host,
        title="Board meeting",
        scheduled_start_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    await harness.service.join(meeting_id=meeting.id, user=host)
    assert get_room_phase(meeting) == "live"


async def test_room_phase_ended(harness: Harness) -> None:
    host = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Board meeting")
    await harness.service.join(meeting_id=meeting.id, user=host)
    await harness.service.end_meeting(meeting_id=meeting.id, acting_user_id=host.id)
    assert get_room_phase(meeting) == "ended"


async def test_extend_duration_requires_host_or_cohost(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(
        host=host, title="Board meeting", scheduled_duration_minutes=30
    )
    await harness.service.join(meeting_id=meeting.id, user=host)
    await harness.service.join(meeting_id=meeting.id, user=other)

    with pytest.raises(MeetingError, match="Only the host or a co-host"):
        await harness.service.extend_duration(
            meeting_id=meeting.id, acting_user_id=other.id, additional_minutes=15
        )


async def test_extend_duration_requires_a_live_meeting(harness: Harness) -> None:
    host = await _make_user(harness)
    meeting = await harness.service.create_meeting(
        host=host, title="Board meeting", scheduled_duration_minutes=30
    )
    with pytest.raises(MeetingError, match="currently live"):
        await harness.service.extend_duration(
            meeting_id=meeting.id, acting_user_id=host.id, additional_minutes=15
        )


async def test_extend_duration_pushes_the_live_deadline_out(harness: Harness) -> None:
    host = await _make_user(harness)
    meeting = await harness.service.create_meeting(
        host=host, title="Board meeting", scheduled_duration_minutes=30
    )
    await harness.service.join(meeting_id=meeting.id, user=host)
    assert meeting.actual_start_at is not None

    original_deadline = get_live_deadline(meeting)
    assert original_deadline == meeting.actual_start_at + timedelta(minutes=30)

    await harness.service.extend_duration(
        meeting_id=meeting.id, acting_user_id=host.id, additional_minutes=15
    )
    extended_deadline = get_live_deadline(meeting)
    assert extended_deadline == meeting.actual_start_at + timedelta(minutes=45)

    # Extending never ends the meeting itself (confirmed decision: alert
    # the host at zero, never auto-end).
    assert meeting.status == "live"


async def test_a_participant_who_leaves_a_live_meeting_can_rejoin(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Board meeting")
    await harness.service.join(meeting_id=meeting.id, user=host)
    await harness.service.join(meeting_id=meeting.id, user=other)

    await harness.service.leave(meeting_id=meeting.id, user_id=other.id)
    rejoin_result = await harness.service.join(meeting_id=meeting.id, user=other)
    assert rejoin_result.access_token is not None


# ---- delete + co-host invite ------------------------------------------------


async def test_delete_meeting_requires_host(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Board meeting")

    with pytest.raises(MeetingError, match="Only the host"):
        await harness.service.delete_meeting(meeting_id=meeting.id, acting_user_id=other.id)


async def test_delete_meeting_removes_it_and_cascades_participants(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Board meeting")
    await harness.service.join(meeting_id=meeting.id, user=host)
    await harness.service.join(meeting_id=meeting.id, user=other)

    await harness.service.delete_meeting(meeting_id=meeting.id, acting_user_id=host.id)

    with pytest.raises(MeetingError, match="No such meeting"):
        await harness.service.get_meeting(meeting.id)
    assert await harness.participants.get_by_meeting_and_user(meeting.id, other.id) is None


async def test_delete_meeting_works_regardless_of_status(harness: Harness) -> None:
    host = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Board meeting")
    await harness.service.join(meeting_id=meeting.id, user=host)
    await harness.service.end_meeting(meeting_id=meeting.id, acting_user_id=host.id)

    await harness.service.delete_meeting(meeting_id=meeting.id, acting_user_id=host.id)
    with pytest.raises(MeetingError, match="No such meeting"):
        await harness.service.get_meeting(meeting.id)


async def test_invite_co_host_requires_host(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    invitee = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Board meeting")

    with pytest.raises(MeetingError, match="Only the host"):
        await harness.service.invite_co_host(
            meeting_id=meeting.id, acting_user_id=other.id, invitee_phone=invitee.phone
        )


async def test_invite_co_host_requires_a_real_account(harness: Harness) -> None:
    host = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Board meeting")

    with pytest.raises(MeetingError, match="No DITSALA account"):
        await harness.service.invite_co_host(
            meeting_id=meeting.id, acting_user_id=host.id, invitee_phone="+27000000000"
        )


async def test_invite_co_host_pre_provisions_the_role_before_they_join(harness: Harness) -> None:
    host = await _make_user(harness)
    invitee = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Board meeting")

    participant = await harness.service.invite_co_host(
        meeting_id=meeting.id, acting_user_id=host.id, invitee_phone=invitee.phone
    )
    assert participant.role == "co_host"
    assert participant.admission_status == "admitted"

    # join() must find and reuse this pre-provisioned row, not create a
    # second, plain-participant one.
    join_result = await harness.service.join(meeting_id=meeting.id, user=invitee)
    assert join_result.participant.id == participant.id
    assert join_result.participant.role == "co_host"


async def test_invite_co_host_promotes_an_existing_participant(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.service.create_meeting(host=host, title="Board meeting")
    join_result = await harness.service.join(meeting_id=meeting.id, user=other)
    assert join_result.participant.role == "participant"

    promoted = await harness.service.invite_co_host(
        meeting_id=meeting.id, acting_user_id=host.id, invitee_phone=other.phone
    )
    assert promoted.id == join_result.participant.id
    assert promoted.role == "co_host"
