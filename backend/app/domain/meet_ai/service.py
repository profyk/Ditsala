"""
Ditsala Meet AI pipeline — docs/DITSALA_MEET_SPEC.md §6, §9 Phase 3.
Transcribes a *finished recording* (via `TranscriptionProvider`) rather
than live per-track audio — see `domain/meet_ai/interfaces.py`'s module
docstring for why. Everything downstream of a stored transcript (notes,
Q&A, search) works the same either way, since it's all read paths over
`meeting_transcripts`/`meeting_ai_notes`, per the parent spec's own
"what did I miss / search are just queries" framing.
"""

import uuid
from dataclasses import dataclass

from app.domain.meet_ai.interfaces import MeetingIntelligenceProvider, TranscriptionProvider
from app.domain.meetings.service import MeetingError
from app.domain.messaging.interfaces import StorageProvider
from app.models.meetings import Meeting, MeetingAiNote, MeetingParticipant, MeetingTranscript
from app.repositories.meetings import (
    MeetingAiNoteRepository,
    MeetingParticipantRepository,
    MeetingRecordingRepository,
    MeetingRepository,
    MeetingTranscriptRepository,
)

_HOST_ROLES = ("host", "co_host")


@dataclass(frozen=True)
class MeetingNotes:
    summary: MeetingAiNote
    decisions: list[MeetingAiNote]
    action_items: list[MeetingAiNote]
    topics: list[MeetingAiNote]


class MeetingIntelligenceService:
    def __init__(
        self,
        *,
        meetings: MeetingRepository,
        participants: MeetingParticipantRepository,
        recordings: MeetingRecordingRepository,
        transcripts: MeetingTranscriptRepository,
        notes: MeetingAiNoteRepository,
        storage_provider: StorageProvider,
        transcription_provider: TranscriptionProvider,
        intelligence_provider: MeetingIntelligenceProvider,
    ) -> None:
        self._meetings = meetings
        self._participants = participants
        self._recordings = recordings
        self._transcripts = transcripts
        self._notes = notes
        self._storage_provider = storage_provider
        self._transcription_provider = transcription_provider
        self._intelligence_provider = intelligence_provider

    async def transcribe_recording(
        self, *, meeting_id: uuid.UUID, acting_user_id: uuid.UUID, recording_id: uuid.UUID
    ) -> list[MeetingTranscript]:
        await self._require_host_or_cohost(meeting_id, acting_user_id)
        recording = await self._recordings.get(recording_id)
        if recording is None or recording.meeting_id != meeting_id:
            raise MeetingError("No such recording on this meeting.")
        if recording.status != "ready" or recording.storage_key is None:
            raise MeetingError("This recording isn't ready to transcribe yet.")

        audio_url = await self._storage_provider.create_download_url(key=recording.storage_key)
        segments = await self._transcription_provider.transcribe_from_url(audio_url=audio_url)

        # Deepgram's diarization only knows speaker indices (0, 1, 2...),
        # not DITSALA identities — mapping index -> the Nth participant
        # to join is a best-effort heuristic, not a guaranteed-correct
        # identification (no per-track audio tap ties a speaker index to
        # a specific LiveKit participant in this post-meeting pipeline).
        participants = await self._participants.list_for_meeting(meeting_id)
        # `joined_at` is tz-aware (set via `datetime.now(UTC)`) but
        # `created_at` (`TimestampMixin`) is a naive `timestamp without
        # time zone` column — sorting a mix of the two straight up raises
        # TypeError, so `joined_at` is normalized to naive here too (same
        # fix CLAUDE.md's Phase 7 notes already applied elsewhere for
        # this exact column-type mismatch).
        participants_by_join_order = sorted(
            participants,
            key=lambda p: (p.joined_at.replace(tzinfo=None) if p.joined_at else p.created_at),
        )

        rows = [
            MeetingTranscript(
                meeting_id=meeting_id,
                speaker_participant_id=_map_speaker(
                    segment.speaker_index, participants_by_join_order
                ),
                text_segment=segment.text,
                started_at_ms=segment.started_at_ms,
                ended_at_ms=segment.ended_at_ms,
            )
            for segment in segments
        ]
        return await self._transcripts.add_many(rows)

    async def list_transcript(self, *, meeting_id: uuid.UUID) -> list[MeetingTranscript]:
        return await self._transcripts.list_for_meeting(meeting_id)

    async def generate_notes(
        self, *, meeting_id: uuid.UUID, acting_user_id: uuid.UUID
    ) -> MeetingNotes:
        await self._require_host_or_cohost(meeting_id, acting_user_id)
        meeting = await self._get_meeting(meeting_id)
        transcript_text = await self._transcript_text(meeting_id)
        if not transcript_text:
            raise MeetingError("No transcript exists yet for this meeting.")

        summary = await self._intelligence_provider.summarize(
            meeting_title=meeting.title, transcript_text=transcript_text
        )
        summary_note = await self._notes.add(
            MeetingAiNote(
                meeting_id=meeting_id, kind="summary", content=summary.executive_summary
            )
        )
        decisions = [
            await self._notes.add(MeetingAiNote(meeting_id=meeting_id, kind="decision", content=c))
            for c in summary.decisions
        ]
        action_items = [
            await self._notes.add(
                MeetingAiNote(meeting_id=meeting_id, kind="action_item", content=c)
            )
            for c in summary.action_items
        ]
        topics = [
            await self._notes.add(MeetingAiNote(meeting_id=meeting_id, kind="topic", content=c))
            for c in summary.topics
        ]
        return MeetingNotes(
            summary=summary_note, decisions=decisions, action_items=action_items, topics=topics
        )

    async def list_notes(self, *, meeting_id: uuid.UUID) -> list[MeetingAiNote]:
        return await self._notes.list_for_meeting(meeting_id)

    async def edit_note(
        self,
        *,
        meeting_id: uuid.UUID,
        note_id: uuid.UUID,
        editor_participant_id: uuid.UUID,
        content: str,
    ) -> MeetingAiNote:
        note = await self._notes.get(note_id)
        if note is None or note.meeting_id != meeting_id:
            raise MeetingError("No such note on this meeting.")
        note.content = content
        note.edited_by_participant_id = editor_participant_id
        return note

    async def ask(self, *, meeting_id: uuid.UUID, question: str) -> str:
        transcript_text = await self._transcript_text(meeting_id)
        if not transcript_text:
            raise MeetingError("No transcript exists yet for this meeting.")
        return await self._intelligence_provider.answer_question(
            transcript_text=transcript_text, question=question
        )

    async def search_meetings(self, *, user_id: uuid.UUID, query: str) -> list[Meeting]:
        return await self._meetings.search_for_user(user_id=user_id, query=query)

    async def _transcript_text(self, meeting_id: uuid.UUID) -> str:
        segments = await self._transcripts.list_for_meeting(meeting_id)
        return "\n".join(segment.text_segment for segment in segments)

    async def _get_meeting(self, meeting_id: uuid.UUID) -> Meeting:
        meeting = await self._meetings.get(meeting_id)
        if meeting is None:
            raise MeetingError("No such meeting.")
        return meeting

    async def _require_host_or_cohost(
        self, meeting_id: uuid.UUID, acting_user_id: uuid.UUID
    ) -> None:
        participant = await self._participants.get_by_meeting_and_user(meeting_id, acting_user_id)
        if participant is None or participant.role not in _HOST_ROLES:
            raise MeetingError("Only the host or a co-host can do this.")


def _map_speaker(
    speaker_index: int | None, participants: list[MeetingParticipant]
) -> uuid.UUID | None:
    if speaker_index is None or not 0 <= speaker_index < len(participants):
        return None
    return participants[speaker_index].id
