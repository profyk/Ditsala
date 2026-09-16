"""
Real Deepgram adapter — docs/DITSALA_MEET_SPEC.md §6, §9 Phase 3.
Deepgram's prerecorded-audio REST API (not the live-streaming websocket
API — see `domain/meet_ai/interfaces.py`'s module docstring for why this
pass transcribes a finished recording rather than a live per-track
stream). The request/response shape here follows Deepgram's publicly
documented `/v1/listen` contract but has not been exercised against a
live Deepgram account in this environment — see docs/SECURITY_GAPS.md,
same caveat as the Stitch/Smile ID adapters.
"""

from typing import Any

import httpx

from app.core.config import Settings
from app.domain.meet_ai.interfaces import TranscriptionProvider, TranscriptSegment

_LISTEN_URL = "https://api.deepgram.com/v1/listen"
_PARAMS = {"model": "nova-2", "diarize": "true", "punctuate": "true", "smart_format": "true"}
# Prerecorded transcription time scales with audio length, not real-time
# playback speed, but a long meeting recording can still take well over
# a minute to process — generous relative to every other adapter's
# timeout in this codebase.
_TIMEOUT_SECONDS = 300.0


class DeepgramTranscriptionProvider(TranscriptionProvider):
    def __init__(self, *, api_key: str) -> None:
        self._api_key = api_key

    @classmethod
    def from_settings(cls, settings: Settings) -> "DeepgramTranscriptionProvider":
        return cls(api_key=settings.deepgram_api_key)

    async def transcribe_from_url(self, *, audio_url: str) -> list[TranscriptSegment]:
        headers = {"Authorization": f"Token {self._api_key}"}
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                _LISTEN_URL, params=_PARAMS, headers=headers, json={"url": audio_url}
            )
            response.raise_for_status()
        payload = response.json()
        words = payload["results"]["channels"][0]["alternatives"][0]["words"]
        return _group_words_into_segments(words)


def _group_words_into_segments(words: list[dict[str, Any]]) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    current_speaker: int | None = None
    current_words: list[str] = []
    current_start_ms = 0
    current_end_ms = 0

    for word in words:
        speaker = word.get("speaker")
        if current_words and speaker != current_speaker:
            segments.append(
                TranscriptSegment(
                    text=" ".join(current_words),
                    started_at_ms=current_start_ms,
                    ended_at_ms=current_end_ms,
                    speaker_index=current_speaker,
                )
            )
            current_words = []
        if not current_words:
            current_start_ms = round(word["start"] * 1000)
            current_speaker = speaker
        current_words.append(word["word"])
        current_end_ms = round(word["end"] * 1000)

    if current_words:
        segments.append(
            TranscriptSegment(
                text=" ".join(current_words),
                started_at_ms=current_start_ms,
                ended_at_ms=current_end_ms,
                speaker_index=current_speaker,
            )
        )
    return segments
