"""
Real end-to-end enforcement tests — a live `PlanService` wired into a
live `MeetingService`, both against real Postgres, exercising the actual
seeded Conference Room plans from migration `b4f7c1a9e6d2` (Free/Pro/
Premium/Enterprise). Where `test_meeting_service.py`'s existing harness
never wires `PlanService` (proving enforcement is a safe no-op when it's
absent), this file proves the opposite: with it wired, guest caps,
duration caps, and tool gates actually fire.

Requires the migrations to have been run against the target database —
same precondition every other real-Postgres test file in this repo has.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.domain.billing.conference_plans import (
    ENTERPRISE_PLAN_CODE,
    FREE_PLAN_CODE,
    PREMIUM_PLAN_CODE,
    PRO_PLAN_CODE,
)
from app.domain.billing.plans import PlanService
from app.domain.meetings.interfaces import RecordingHandle
from app.domain.meetings.service import MeetingError, MeetingService
from app.domain.messaging.interfaces import StorageProvider
from app.domain.translation.service import TranslationService
from app.models.accounts import User
from app.repositories.admin import AuditLogRepository, SystemConfigRepository
from app.repositories.billing import EntitlementRepository, PlanPriceRepository, PlanRepository
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


class StubRoomProvider(LiveKitRoomProvider):
    """Same reasoning as `test_meeting_service.py`'s own stub — real
    token-minting (no network call) stays real; `start_recording` alone
    is overridden since this file's one recording test needs to get past
    the tool gate and see a *result*, not a real LiveKit Egress call
    (no LiveKit server exists in this environment)."""

    def __init__(self) -> None:
        super().__init__(
            api_key=TEST_LIVEKIT_KEY, api_secret=TEST_LIVEKIT_SECRET, livekit_url="wss://test"
        )

    async def start_recording(self, *, room_name: str, s3_key: str) -> RecordingHandle:
        return RecordingHandle(egress_id=f"EG_{uuid.uuid4().hex}", status="processing")


@dataclass
class Harness:
    meetings: MeetingService
    plans: PlanService
    users: UserRepository


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
    plans = PlanService(
        plans=PlanRepository(session),
        plan_prices=PlanPriceRepository(session),
        entitlements=EntitlementRepository(session),
        audit_log=AuditLogRepository(session),
        users=users,
    )
    translation_service = TranslationService(
        translation_requests=TranslationRequestRepository(session),
        translation_usage=TranslationUsageRepository(session),
        user_language_preferences=UserLanguagePreferenceRepository(session),
        interpreter_sessions=InterpreterSessionRepository(session),
        system_config=SystemConfigRepository(session),
        provider=MockTranslationProvider(),
    )
    meetings = MeetingService(
        meetings=MeetingRepository(session),
        participants=MeetingParticipantRepository(session),
        room_provider=StubRoomProvider(),
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
        conference_language_preferences=ConferenceLanguagePreferenceRepository(session),
        translation_service=translation_service,
        users=users,
        plans=plans,
    )
    return Harness(meetings=meetings, plans=plans, users=users)


async def _make_user(harness: Harness, **overrides: object) -> User:
    fields: dict[str, object] = {
        "email": f"{uuid.uuid4()}@example.com",
        "phone": f"+27{uuid.uuid4().int % 10**9}",
        "display_name": "Conference Plan Test User",
        "date_of_birth": datetime(1990, 1, 1),
        "national_id_hash": uuid.uuid4().hex,
        "account_state": "active",
        **overrides,
    }
    return await harness.users.add(User(**fields))


async def _make_admin_id(session: AsyncSession) -> uuid.UUID:
    # set_user_conference_plan only needs a UUID for the audit log's
    # actor_id — no FK to admin_users, so a bare uuid4 is a legitimate,
    # minimal stand-in here (unlike test_plan_service.py's `admin_id`
    # fixture, which needs a *real* AdminUser row only because some of
    # its other tests read the audit log back via admin-scoped queries
    # this file doesn't exercise).
    return uuid.uuid4()


async def test_default_free_plan_clamps_duration_and_guests(harness: Harness) -> None:
    host = await _make_user(harness)
    # No conference_plan_code set -> resolves to the seeded "conference_free"
    # plan (5 guests, 40-minute cap — see migration b4f7c1a9e6d2).
    meeting = await harness.meetings.create_meeting(
        host=host, title="Standup", scheduled_duration_minutes=999
    )
    assert meeting.scheduled_duration_minutes == 40
    assert meeting.max_participants == 5


async def test_pro_plan_allows_longer_meetings(harness: Harness) -> None:
    host = await _make_user(harness)
    admin_id = await _make_admin_id(harness.users.session)
    await harness.plans.set_user_conference_plan(
        admin_id=admin_id, user_id=host.id, plan_code=PRO_PLAN_CODE, reason="test upgrade"
    )
    meeting = await harness.meetings.create_meeting(
        host=host, title="Quarterly review", scheduled_duration_minutes=120
    )
    assert meeting.scheduled_duration_minutes == 120  # under Pro's 180-minute cap
    assert meeting.max_participants == 25


async def test_guest_join_rejected_once_at_capacity(harness: Harness) -> None:
    host = await _make_user(harness)
    admin_id = await _make_admin_id(harness.users.session)
    # Free tier caps at 5 guests total (host + 4 more) — force it down
    # further isn't needed; just fill to the real seeded cap.
    await harness.plans.set_user_conference_plan(
        admin_id=admin_id, user_id=host.id, plan_code=FREE_PLAN_CODE, reason="test"
    )
    meeting = await harness.meetings.create_meeting(host=host, title="Small room")
    # A participant row only occupies a seat once actually connected
    # (see entitlements.count_active_participants) — the host's own row
    # from create_meeting doesn't count until they call join().
    await harness.meetings.join(meeting_id=meeting.id, user=host)

    for i in range(4):  # host now occupies 1 of 5 seats
        await harness.meetings.guest_join(meeting_id=meeting.id, guest_display_name=f"Guest {i}")

    with pytest.raises(MeetingError, match="guest limit"):
        await harness.meetings.guest_join(meeting_id=meeting.id, guest_display_name="One too many")


async def test_a_guest_who_leaves_frees_up_their_seat(harness: Harness) -> None:
    """The actual real-world bug report this guards against: repeated
    testing (or real guests reconnecting) used to permanently exhaust a
    Free-tier meeting's 5-guest cap even with nobody left in the room,
    because `guest_join` mints a brand-new participant row every call
    and nothing ever marked an earlier one as having left. Filling the
    cap, having everyone leave, then confirming a fresh guest can still
    get in is the real end-to-end proof, not just the counting-function
    unit tests in test_conference_entitlements.py."""
    host = await _make_user(harness)
    admin_id = await _make_admin_id(harness.users.session)
    await harness.plans.set_user_conference_plan(
        admin_id=admin_id, user_id=host.id, plan_code=FREE_PLAN_CODE, reason="test"
    )
    meeting = await harness.meetings.create_meeting(host=host, title="Small room")
    await harness.meetings.join(meeting_id=meeting.id, user=host)

    guests = []
    for i in range(4):
        result = await harness.meetings.guest_join(
            meeting_id=meeting.id, guest_display_name=f"Guest {i}"
        )
        guests.append(result.participant)

    with pytest.raises(MeetingError, match="guest limit"):
        await harness.meetings.guest_join(meeting_id=meeting.id, guest_display_name="One too many")

    # Every guest actually leaves — the same public, participant_id-based
    # call apps/meet's onDisconnected handler makes for a real guest.
    for guest in guests:
        await harness.meetings.mark_participant_left(
            meeting_id=meeting.id, participant_id=guest.id
        )

    # The cap is free again — a new guest gets in without needing the
    # host to upgrade plans or manually clean anything up.
    fresh = await harness.meetings.guest_join(
        meeting_id=meeting.id, guest_display_name="Finally in"
    )
    assert fresh.access_token is not None


async def test_extend_duration_rejects_beyond_plan_cap(harness: Harness) -> None:
    host = await _make_user(harness)
    admin_id = await _make_admin_id(harness.users.session)
    await harness.plans.set_user_conference_plan(
        admin_id=admin_id, user_id=host.id, plan_code=PRO_PLAN_CODE, reason="test"
    )
    meeting = await harness.meetings.create_meeting(
        host=host, title="Long one", scheduled_duration_minutes=170
    )
    join = await harness.meetings.join(meeting_id=meeting.id, user=host)
    assert join.access_token is not None
    meeting.status = "live"  # extend_duration requires a live meeting

    with pytest.raises(MeetingError, match="exceed"):
        await harness.meetings.extend_duration(
            meeting_id=meeting.id, acting_user_id=host.id, additional_minutes=30
        )  # 170 + 30 = 200 > Pro's 180-minute cap


async def test_recording_gated_behind_plan_tool(harness: Harness) -> None:
    host = await _make_user(harness)
    admin_id = await _make_admin_id(harness.users.session)
    await harness.plans.set_user_conference_plan(
        admin_id=admin_id, user_id=host.id, plan_code=FREE_PLAN_CODE, reason="test"
    )
    meeting = await harness.meetings.create_meeting(host=host, title="No recording here")

    with pytest.raises(MeetingError, match="not included"):
        await harness.meetings.start_recording(meeting_id=meeting.id, acting_user_id=host.id)

    # Upgrading to Pro (which includes "recording") should unblock it
    # immediately — tool gates re-read live, unlike the snapshotted guest cap.
    await harness.plans.set_user_conference_plan(
        admin_id=admin_id, user_id=host.id, plan_code=PRO_PLAN_CODE, reason="upgrade"
    )
    recording = await harness.meetings.start_recording(
        meeting_id=meeting.id, acting_user_id=host.id
    )
    assert recording.status == "processing"


async def test_breakout_rooms_gated_behind_premium(harness: Harness) -> None:
    host = await _make_user(harness)
    admin_id = await _make_admin_id(harness.users.session)
    await harness.plans.set_user_conference_plan(
        admin_id=admin_id, user_id=host.id, plan_code=PRO_PLAN_CODE, reason="test"
    )
    meeting = await harness.meetings.create_meeting(host=host, title="Pro tier")

    with pytest.raises(MeetingError, match="not included"):
        await harness.meetings.create_breakout_rooms(
            meeting_id=meeting.id, acting_user_id=host.id, names=["Room A"]
        )

    await harness.plans.set_user_conference_plan(
        admin_id=admin_id, user_id=host.id, plan_code=PREMIUM_PLAN_CODE, reason="upgrade"
    )
    rooms = await harness.meetings.create_breakout_rooms(
        meeting_id=meeting.id, acting_user_id=host.id, names=["Room A", "Room B"]
    )
    assert len(rooms) == 2


async def test_analytics_gated_and_reports_real_attendance(harness: Harness) -> None:
    host = await _make_user(harness)
    admin_id = await _make_admin_id(harness.users.session)
    await harness.plans.set_user_conference_plan(
        admin_id=admin_id, user_id=host.id, plan_code=PREMIUM_PLAN_CODE, reason="test"
    )
    meeting = await harness.meetings.create_meeting(host=host, title="Analyzed meeting")
    await harness.meetings.join(meeting_id=meeting.id, user=host)
    await harness.meetings.guest_join(meeting_id=meeting.id, guest_display_name="A Guest")

    report = await harness.meetings.get_meeting_analytics(
        meeting_id=meeting.id, acting_user_id=host.id
    )
    assert report.unique_attendees == 2
    assert report.guest_attendees == 1


async def test_enterprise_plan_is_unlimited(harness: Harness) -> None:
    host = await _make_user(harness)
    admin_id = await _make_admin_id(harness.users.session)
    await harness.plans.set_user_conference_plan(
        admin_id=admin_id, user_id=host.id, plan_code=ENTERPRISE_PLAN_CODE, reason="test"
    )
    meeting = await harness.meetings.create_meeting(
        host=host, title="Big event", scheduled_duration_minutes=10_000
    )
    assert meeting.scheduled_duration_minutes == 10_000  # never clamped
    assert meeting.max_participants is None  # never capped


async def test_set_user_conference_plan_rejects_unknown_code(harness: Harness) -> None:
    from app.domain.billing.plans import PlanError

    host = await _make_user(harness)
    admin_id = await _make_admin_id(harness.users.session)
    with pytest.raises(PlanError, match="not an active conference plan"):
        await harness.plans.set_user_conference_plan(
            admin_id=admin_id, user_id=host.id, plan_code="not-a-real-plan", reason="typo"
        )
