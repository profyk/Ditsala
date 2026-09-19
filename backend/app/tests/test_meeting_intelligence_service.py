"""
Unit tests for Ditsala Meet Phase 3 (docs/DITSALA_MEET_SPEC.md §9) — real
Postgres (including the generated `tsvector` search columns), a real
`S3StorageProvider` (presigned-URL generation is a local computation, no
network call — same reasoning `test_meeting_service.py` uses for real
LiveKit token minting), and stub `TranscriptionProvider`/
`MeetingIntelligenceProvider`s standing in for Deepgram/Claude, since no
live credentials for either exist in this environment.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.domain.meet_ai.interfaces import (
    MeetingIntelligenceProvider,
    MeetingSummary,
    TranscriptionProvider,
    TranscriptSegment,
)
from app.domain.meet_ai.service import MeetingIntelligenceService
from app.domain.meetings.service import MeetingError, MeetingService
from app.models.accounts import User
from app.models.meetings import MeetingRecording
from app.repositories.meetings import (
    BreakoutRoomParticipantRepository,
    BreakoutRoomRepository,
    MeetingAiNoteRepository,
    MeetingDocumentRepository,
    MeetingMessageRepository,
    MeetingParticipantRepository,
    MeetingPollRepository,
    MeetingPollVoteRepository,
    MeetingQuestionRepository,
    MeetingRecordingRepository,
    MeetingRegistrationRepository,
    MeetingRepository,
    MeetingTranscriptRepository,
)
from app.repositories.users import UserRepository
from app.services.storage.s3 import S3StorageProvider
from app.tests.test_meeting_service import StubRoomProvider


class StubTranscriptionProvider(TranscriptionProvider):
    def __init__(self, segments: list[TranscriptSegment]) -> None:
        self.segments = segments
        self.requested_urls: list[str] = []

    async def transcribe_from_url(self, *, audio_url: str) -> list[TranscriptSegment]:
        self.requested_urls.append(audio_url)
        return self.segments


class StubIntelligenceProvider(MeetingIntelligenceProvider):
    def __init__(self, summary: MeetingSummary, answer: str = "Yes, that was covered.") -> None:
        self._summary = summary
        self._answer = answer
        self.summarize_calls: list[str] = []
        self.question_calls: list[str] = []

    async def summarize(self, *, meeting_title: str, transcript_text: str) -> MeetingSummary:
        self.summarize_calls.append(transcript_text)
        return self._summary

    async def answer_question(self, *, transcript_text: str, question: str) -> str:
        self.question_calls.append(question)
        return self._answer


@dataclass
class Harness:
    meeting_service: MeetingService
    intel_service: MeetingIntelligenceService
    users: UserRepository
    participants: MeetingParticipantRepository
    recordings: MeetingRecordingRepository
    transcription: StubTranscriptionProvider
    intelligence: StubIntelligenceProvider


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
    recordings = MeetingRecordingRepository(session)
    meeting_service = MeetingService(
        meetings=MeetingRepository(session),
        participants=participants,
        room_provider=StubRoomProvider(),
        recordings=recordings,
        messages=MeetingMessageRepository(session),
        polls=MeetingPollRepository(session),
        poll_votes=MeetingPollVoteRepository(session),
        questions=MeetingQuestionRepository(session),
        breakout_rooms=BreakoutRoomRepository(session),
        breakout_room_participants=BreakoutRoomParticipantRepository(session),
        registrations=MeetingRegistrationRepository(session),
        documents=MeetingDocumentRepository(session),
        storage_provider=S3StorageProvider(
            bucket="test-bucket",
            region="us-east-1",
            access_key_id="test",
            secret_access_key="test",
            endpoint_url="",
            url_ttl_minutes=15,
        ),
    )
    transcription = StubTranscriptionProvider(
        [
            TranscriptSegment(
                text="Let's ship it.", started_at_ms=0, ended_at_ms=1500, speaker_index=0
            ),
            TranscriptSegment(
                text="Agreed, I'll write the tests.",
                started_at_ms=1500,
                ended_at_ms=3200,
                speaker_index=1,
            ),
        ]
    )
    intelligence = StubIntelligenceProvider(
        MeetingSummary(
            executive_summary="The team agreed to ship the feature.",
            decisions=["Ship the feature this week."],
            action_items=["Write the tests."],
            topics=["Release planning"],
        )
    )
    intel_service = MeetingIntelligenceService(
        meetings=MeetingRepository(session),
        participants=participants,
        recordings=recordings,
        transcripts=MeetingTranscriptRepository(session),
        notes=MeetingAiNoteRepository(session),
        storage_provider=S3StorageProvider(
            bucket="test-bucket",
            region="us-east-1",
            access_key_id="test",
            secret_access_key="test",
            endpoint_url="",
            url_ttl_minutes=15,
        ),
        transcription_provider=transcription,
        intelligence_provider=intelligence,
    )
    return Harness(
        meeting_service=meeting_service,
        intel_service=intel_service,
        users=UserRepository(session),
        participants=participants,
        recordings=recordings,
        transcription=transcription,
        intelligence=intelligence,
    )


async def _make_user(harness: Harness, **overrides: object) -> User:
    fields: dict[str, object] = {
        "email": f"{uuid.uuid4()}@example.com",
        "phone": f"+27{uuid.uuid4().int % 10**9}",
        "display_name": "Meet AI Test User",
        "date_of_birth": datetime(1990, 1, 1),
        "national_id_hash": uuid.uuid4().hex,
        "account_state": "active",
        **overrides,
    }
    return await harness.users.add(User(**fields))


async def test_transcribe_recording_maps_speakers_by_join_order(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.meeting_service.create_meeting(host=host, title="Sprint planning")
    # Both explicitly join (as a real host client would) so `joined_at`
    # — not `created_at`, which is frozen to this test's single
    # transaction start time via Postgres's `now()` and so can't order
    # same-transaction rows — gives a well-defined join order to map
    # Deepgram's speaker indices against.
    await harness.meeting_service.join(meeting_id=meeting.id, user=host)
    other_result = await harness.meeting_service.join(meeting_id=meeting.id, user=other)
    host_participant = await harness.participants.get_by_meeting_and_user(meeting.id, host.id)
    assert host_participant is not None

    recording = await harness.recordings.add(
        MeetingRecording(
            meeting_id=meeting.id,
            egress_id=f"EG_{uuid.uuid4().hex}",
            storage_key="meetings/x/recordings/x.mp4",
            status="ready",
        )
    )

    segments = await harness.intel_service.transcribe_recording(
        meeting_id=meeting.id, acting_user_id=host.id, recording_id=recording.id
    )

    assert len(segments) == 2
    assert segments[0].speaker_participant_id == host_participant.id
    assert segments[1].speaker_participant_id == other_result.participant.id
    assert harness.transcription.requested_urls  # a real presigned URL was requested


async def test_transcribe_recording_requires_host_and_ready_status(harness: Harness) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    meeting = await harness.meeting_service.create_meeting(host=host, title="Standup")
    await harness.meeting_service.join(meeting_id=meeting.id, user=other)


    processing_recording = await harness.recordings.add(
        MeetingRecording(
            meeting_id=meeting.id, egress_id=f"EG_{uuid.uuid4().hex}", status="processing"
        )
    )

    with pytest.raises(MeetingError, match="host or a co-host"):
        await harness.intel_service.transcribe_recording(
            meeting_id=meeting.id, acting_user_id=other.id, recording_id=processing_recording.id
        )
    with pytest.raises(MeetingError, match="isn't ready"):
        await harness.intel_service.transcribe_recording(
            meeting_id=meeting.id, acting_user_id=host.id, recording_id=processing_recording.id
        )


async def test_generate_notes_requires_a_transcript_and_writes_all_note_kinds(
    harness: Harness,
) -> None:
    host = await _make_user(harness)
    meeting = await harness.meeting_service.create_meeting(host=host, title="Sprint planning")

    with pytest.raises(MeetingError, match="No transcript"):
        await harness.intel_service.generate_notes(meeting_id=meeting.id, acting_user_id=host.id)


    recording = await harness.recordings.add(
        MeetingRecording(
            meeting_id=meeting.id,
            egress_id=f"EG_{uuid.uuid4().hex}",
            storage_key="k",
            status="ready",
        )
    )
    await harness.intel_service.transcribe_recording(
        meeting_id=meeting.id, acting_user_id=host.id, recording_id=recording.id
    )

    notes = await harness.intel_service.generate_notes(
        meeting_id=meeting.id, acting_user_id=host.id
    )
    assert notes.summary.kind == "summary"
    assert [n.content for n in notes.decisions] == ["Ship the feature this week."]
    assert [n.content for n in notes.action_items] == ["Write the tests."]
    assert [n.content for n in notes.topics] == ["Release planning"]

    all_notes = await harness.intel_service.list_notes(meeting_id=meeting.id)
    assert len(all_notes) == 4


async def test_edit_note_records_the_editor(harness: Harness) -> None:
    host = await _make_user(harness)
    meeting = await harness.meeting_service.create_meeting(host=host, title="Standup")
    host_participant = await harness.participants.get_by_meeting_and_user(meeting.id, host.id)
    assert host_participant is not None


    recording = await harness.recordings.add(
        MeetingRecording(
            meeting_id=meeting.id,
            egress_id=f"EG_{uuid.uuid4().hex}",
            storage_key="k",
            status="ready",
        )
    )
    await harness.intel_service.transcribe_recording(
        meeting_id=meeting.id, acting_user_id=host.id, recording_id=recording.id
    )
    notes = await harness.intel_service.generate_notes(
        meeting_id=meeting.id, acting_user_id=host.id
    )

    edited = await harness.intel_service.edit_note(
        meeting_id=meeting.id,
        note_id=notes.summary.id,
        editor_participant_id=host_participant.id,
        content="Corrected summary.",
    )
    assert edited.content == "Corrected summary."
    assert edited.edited_by_participant_id == host_participant.id


async def test_ask_requires_a_transcript_and_returns_the_provider_answer(
    harness: Harness,
) -> None:
    host = await _make_user(harness)
    meeting = await harness.meeting_service.create_meeting(host=host, title="Standup")

    with pytest.raises(MeetingError, match="No transcript"):
        await harness.intel_service.ask(meeting_id=meeting.id, question="What did I miss?")


    recording = await harness.recordings.add(
        MeetingRecording(
            meeting_id=meeting.id,
            egress_id=f"EG_{uuid.uuid4().hex}",
            storage_key="k",
            status="ready",
        )
    )
    await harness.intel_service.transcribe_recording(
        meeting_id=meeting.id, acting_user_id=host.id, recording_id=recording.id
    )

    answer = await harness.intel_service.ask(meeting_id=meeting.id, question="What did I miss?")
    assert answer == "Yes, that was covered."
    assert harness.intelligence.question_calls == ["What did I miss?"]


async def test_search_meetings_is_scoped_to_the_searching_users_own_meetings(
    harness: Harness,
) -> None:
    host = await _make_user(harness)
    other = await _make_user(harness)
    unrelated = await _make_user(harness)
    unique = uuid.uuid4().hex[:12]
    meeting = await harness.meeting_service.create_meeting(
        host=host, title=f"Quarterly Roadmap Sync {unique}"
    )
    await harness.meeting_service.join(meeting_id=meeting.id, user=other)

    host_results = await harness.intel_service.search_meetings(user_id=host.id, query=unique)
    other_results = await harness.intel_service.search_meetings(user_id=other.id, query=unique)
    unrelated_results = await harness.intel_service.search_meetings(
        user_id=unrelated.id, query=unique
    )

    assert [m.id for m in host_results] == [meeting.id]
    assert [m.id for m in other_results] == [meeting.id]
    assert unrelated_results == []
