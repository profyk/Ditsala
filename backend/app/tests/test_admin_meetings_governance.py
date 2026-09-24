"""
Unit tests for `AdminMeetingGovernanceService` — real Postgres, real
`MeetingService` underneath (delegated to for the actual extend/end
mutations). Exercises the thing that didn't exist before this session:
admin visibility into meetings platform-wide, and admin override of a
meeting that isn't theirs.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.domain.admin.meetings_governance import (
    AdminMeetingGovernanceService,
    MeetingGovernanceError,
)
from app.domain.billing.plans import PlanService
from app.domain.meetings.service import MeetingService
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


class StubRoomProvider(LiveKitRoomProvider):
    """Real token-minting (no network call) stays real; delete_room alone
    is overridden since admin_end_meeting now calls it and there's no
    LiveKit server in this environment to reach — same reasoning as the
    other two RoomProvider stubs in test_meeting_service.py and
    test_meeting_conference_plan_enforcement.py."""

    def __init__(self) -> None:
        super().__init__(
            api_key=TEST_LIVEKIT_KEY, api_secret=TEST_LIVEKIT_SECRET, livekit_url="wss://test"
        )
        self.deleted_rooms: list[str] = []

    async def delete_room(self, *, room_name: str) -> None:
        self.deleted_rooms.append(room_name)


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
    governance: AdminMeetingGovernanceService
    meetings: MeetingService
    users: UserRepository
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
    plans = PlanService(
        plans=PlanRepository(session),
        plan_prices=PlanPriceRepository(session),
        entitlements=EntitlementRepository(session),
        audit_log=AuditLogRepository(session),
        users=users,
    )
    meetings_repo = MeetingRepository(session)
    participants_repo = MeetingParticipantRepository(session)
    translation_service = TranslationService(
        translation_requests=TranslationRequestRepository(session),
        translation_usage=TranslationUsageRepository(session),
        user_language_preferences=UserLanguagePreferenceRepository(session),
        interpreter_sessions=InterpreterSessionRepository(session),
        system_config=SystemConfigRepository(session),
        provider=MockTranslationProvider(),
    )
    meeting_service = MeetingService(
        meetings=meetings_repo,
        participants=participants_repo,
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
    audit_log = AuditLogRepository(session)
    governance = AdminMeetingGovernanceService(
        meetings=meetings_repo,
        participants=participants_repo,
        meeting_service=meeting_service,
        audit_log=audit_log,
    )
    return Harness(
        governance=governance, meetings=meeting_service, users=users, audit_log=audit_log
    )


async def _make_user(harness: Harness, **overrides: object) -> User:
    fields: dict[str, object] = {
        "email": f"{uuid.uuid4()}@example.com",
        "phone": f"+27{uuid.uuid4().int % 10**9}",
        "display_name": "Governance Test Host",
        "date_of_birth": datetime(1990, 1, 1),
        "national_id_hash": uuid.uuid4().hex,
        "account_state": "active",
        **overrides,
    }
    return await harness.users.add(User(**fields))


async def test_list_live_and_scheduled_spans_every_host(harness: Harness) -> None:
    host_a = await _make_user(harness)
    host_b = await _make_user(harness)
    meeting_a = await harness.meetings.create_meeting(host=host_a, title="Team A standup")
    meeting_b = await harness.meetings.create_meeting(host=host_b, title="Team B standup")

    items = await harness.governance.list_live_and_scheduled()
    ids = {item.meeting.id for item in items}
    assert meeting_a.id in ids
    assert meeting_b.id in ids


async def test_admin_can_extend_a_meeting_that_is_not_theirs(harness: Harness) -> None:
    host = await _make_user(harness)
    admin_id = uuid.uuid4()
    meeting = await harness.meetings.create_meeting(
        host=host, title="Board meeting", scheduled_duration_minutes=60
    )
    await harness.meetings.join(meeting_id=meeting.id, user=host)
    # Live status is required by MeetingService.admin_extend_duration.
    meeting.status = "live"

    updated = await harness.governance.extend_meeting(
        admin_id=admin_id, meeting_id=meeting.id, additional_minutes=30, reason="ran over"
    )
    assert updated.duration_extended_minutes == 30

    entries = await harness.audit_log.list_for_target("meeting", meeting.id)
    actions = [e.action for e in entries]
    assert "admin.meeting.extended" in actions
    extended_entry = next(e for e in entries if e.action == "admin.meeting.extended")
    assert extended_entry.metadata_json == {"additional_minutes": 30, "reason": "ran over"}


async def test_admin_can_end_a_meeting_that_is_not_theirs(harness: Harness) -> None:
    host = await _make_user(harness)
    admin_id = uuid.uuid4()
    meeting = await harness.meetings.create_meeting(host=host, title="Standup")

    ended = await harness.governance.end_meeting(
        admin_id=admin_id, meeting_id=meeting.id, reason="policy violation reported"
    )
    assert ended.status == "ended"
    assert ended.actual_end_at is not None

    entries = await harness.audit_log.list_for_target("meeting", meeting.id)
    assert any(e.action == "admin.meeting.ended" for e in entries)


async def test_extend_rejects_unknown_meeting(harness: Harness) -> None:
    with pytest.raises(MeetingGovernanceError):
        await harness.governance.extend_meeting(
            admin_id=uuid.uuid4(),
            meeting_id=uuid.uuid4(),
            additional_minutes=15,
            reason="test",
        )


async def test_admin_analytics_reports_real_attendance(harness: Harness) -> None:
    host = await _make_user(harness)
    meeting = await harness.meetings.create_meeting(host=host, title="Analyzed by admin")
    await harness.meetings.join(meeting_id=meeting.id, user=host)
    await harness.meetings.guest_join(meeting_id=meeting.id, guest_display_name="A Guest")

    report = await harness.governance.get_analytics(meeting.id)
    assert report.unique_attendees == 2
    assert report.as_of.tzinfo is not None
    assert report.as_of <= datetime.now(UTC)
