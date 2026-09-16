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
from app.domain.meetings.service import MeetingError, MeetingService
from app.models.accounts import User
from app.repositories.meetings import MeetingParticipantRepository, MeetingRepository
from app.repositories.users import UserRepository
from app.services.meet.livekit import LiveKitRoomProvider

TEST_LIVEKIT_KEY = "test-key-0123456789"
TEST_LIVEKIT_SECRET = "test-secret-0123456789-0123456789"


@dataclass
class Harness:
    service: MeetingService
    users: UserRepository
    participants: MeetingParticipantRepository


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
    participants = MeetingParticipantRepository(session)
    service = MeetingService(
        meetings=MeetingRepository(session),
        participants=participants,
        room_provider=LiveKitRoomProvider(
            api_key=TEST_LIVEKIT_KEY, api_secret=TEST_LIVEKIT_SECRET, livekit_url="wss://test"
        ),
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
