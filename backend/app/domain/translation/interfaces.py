"""
Ditsala VIP translation — real-adapter-behind-an-interface, same pattern
every external dependency in this codebase uses (Working Rule 4). Unlike
`domain/meet_ai/interfaces.py`'s Deepgram/Claude adapters, translation
*does* get a genuine dev-only mock (`services/translation/mock.py`) rather
than "a real key or none" — text translation is the feature every other
VIP screen depends on to be testable at all, so a MockTranslationProvider
exists specifically to exercise the full chat/interpreter workflow without
an Azure account. It is refused outright when ENVIRONMENT=production
(`services/factory.py`), same guard `KYC_PROVIDER=bypass` already has.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TranslationResult:
    original_text: str
    translated_text: str
    source_language: str  # resolved, even when auto-detected
    target_language: str
    provider: str
    status: str  # "completed" | "failed"
    error_message: str | None = None


class TranslationProvider(Protocol):
    async def translate(
        self, *, text: str, source_language: str | None, target_language: str
    ) -> TranslationResult:
        """`source_language=None` means auto-detect — the provider resolves
        and returns the language it actually detected/used."""
        ...

    async def detect_language(self, *, text: str) -> str:
        ...
