"""
Ditsala Meet AI pipeline — docs/DITSALA_MEET_SPEC.md §6, §9 Phase 3.

Real-adapter-behind-an-interface, same pattern every other external
dependency in this codebase uses (Working Rule 4) — but this pass is a
post-meeting pipeline (transcribe the finished recording, then
summarize), not a live in-meeting one: see this module's own service
docstring and `docs/SECURITY_GAPS.md` for why live per-track streaming
transcription (a LiveKit Agents worker joining the room as a hidden
participant) isn't built here.

No `Sandbox*` adapter for either provider — like `RoomProvider`
(`domain/meetings/interfaces.py`), both Deepgram's and Anthropic's APIs
are the same real endpoint in test and production; there's no vendor-
provided sandbox mode to switch to, only a real key or none.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TranscriptSegment:
    text: str
    started_at_ms: int
    ended_at_ms: int
    # Deepgram's own diarization speaker index (0, 1, 2...) — the caller
    # maps this back to a `MeetingParticipant` by join order, since
    # Deepgram has no notion of DITSALA identities.
    speaker_index: int | None


class TranscriptionProvider(Protocol):
    async def transcribe_from_url(self, *, audio_url: str) -> list[TranscriptSegment]:
        """
        Transcribes a complete audio/video file already reachable at
        `audio_url` (a presigned S3 GET URL — the recording's own
        `StorageProvider.create_download_url`, §8's "reuse, don't
        rewrite"). The provider fetches the bytes itself; DITSALA's
        backend never downloads or holds the recording in memory.
        """
        ...


@dataclass(frozen=True)
class MeetingSummary:
    executive_summary: str
    decisions: list[str]
    action_items: list[str]
    topics: list[str]


class MeetingIntelligenceProvider(Protocol):
    async def summarize(self, *, meeting_title: str, transcript_text: str) -> MeetingSummary:
        """Produces structured notes (§15) from the full transcript-so-far."""
        ...

    async def answer_question(self, *, transcript_text: str, question: str) -> str:
        """§17 "what did I miss" / in-meeting Q&A against the transcript."""
        ...
