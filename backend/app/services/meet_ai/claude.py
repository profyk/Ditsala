"""
Real Claude adapter — docs/DITSALA_MEET_SPEC.md §6, §9 Phase 3. Uses the
`anthropic` Python SDK's Messages API directly (its shape confirmed via
live introspection of the installed package: `messages.create(model=,
max_tokens=, messages=[...])` returning a `Message` whose `.content` is
a list of blocks with a `.text` field on text blocks). Not exercised
against a live Anthropic account with a real API key in this
environment — see docs/SECURITY_GAPS.md.
"""

import json

from anthropic import AsyncAnthropic
from anthropic.types import Message

from app.core.config import Settings
from app.domain.meet_ai.interfaces import MeetingIntelligenceProvider, MeetingSummary

_SUMMARY_MAX_TOKENS = 2000
_ANSWER_MAX_TOKENS = 1000

_SUMMARY_SYSTEM_PROMPT = (
    "You are DITSALA Meet's meeting-notes assistant. Given a meeting "
    "transcript, produce a JSON object with exactly these keys: "
    '"executive_summary" (a short paragraph), "decisions" (array of '
    'strings), "action_items" (array of strings), "topics" (array of '
    "strings). Respond with ONLY the JSON object, no markdown fences, "
    "no other text."
)


class ClaudeMeetingIntelligenceProvider(MeetingIntelligenceProvider):
    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    @classmethod
    def from_settings(cls, settings: Settings) -> "ClaudeMeetingIntelligenceProvider":
        return cls(api_key=settings.anthropic_api_key, model=settings.anthropic_model)

    async def summarize(self, *, meeting_title: str, transcript_text: str) -> MeetingSummary:
        message = await self._client.messages.create(
            model=self._model,
            max_tokens=_SUMMARY_MAX_TOKENS,
            system=_SUMMARY_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Meeting title: {meeting_title}\n\nTranscript:\n{transcript_text}"
                    ),
                }
            ],
        )
        data = json.loads(_extract_text(message).strip())
        return MeetingSummary(
            executive_summary=data["executive_summary"],
            decisions=list(data["decisions"]),
            action_items=list(data["action_items"]),
            topics=list(data["topics"]),
        )

    async def answer_question(self, *, transcript_text: str, question: str) -> str:
        message = await self._client.messages.create(
            model=self._model,
            max_tokens=_ANSWER_MAX_TOKENS,
            system=(
                "You answer questions about a meeting using only the transcript "
                "provided. If the transcript doesn't cover the answer, say so plainly."
            ),
            messages=[
                {
                    "role": "user",
                    "content": f"Transcript:\n{transcript_text}\n\nQuestion: {question}",
                }
            ],
        )
        return _extract_text(message).strip()


def _extract_text(message: Message) -> str:
    block = message.content[0]
    if block.type != "text":
        raise ValueError(f"Expected a text content block, got {block.type!r}.")
    return block.text
