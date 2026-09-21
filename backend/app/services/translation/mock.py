"""
MockTranslationProvider — DEV-ONLY. Exercises the full VIP chat/interpreter
workflow with no Azure account. `services/factory.py` refuses to construct
this when `ENVIRONMENT=production`, no matter how `TRANSLATION_PROVIDER` is
set (same guard `KYC_PROVIDER=bypass` already has) — mock translations must
never ship live, per explicit product instruction.
"""

import re

from app.domain.translation.interfaces import TranslationProvider, TranslationResult

PROVIDER_NAME = "mock"

# A handful of exact phrases from the product spec itself, so testing with
# the spec's own examples produces the spec's own expected output — a
# real, demonstrable round trip, not just a placeholder string.
_KNOWN_PHRASES: dict[tuple[str, str, str], str] = {
    ("zh", "zu", "你好，很高兴认识你。"): "Sawubona, ngiyajabula ukukwazi.",
    ("zu", "zh", "Sawubona, ngiyajabula ukukwazi."): "你好，很高兴认识你。",
    ("zu", "zh", "Ngifuna ukukubonga ngokusiza kwenu."): "我想感谢你们的帮助。",
    ("zh", "en", "你好，很高兴认识你。"): "Hello, nice to meet you.",
    ("en", "zh", "Hello, nice to meet you."): "你好，很高兴认识你。",
    ("zu", "en", "Sawubona, ngiyajabula ukukwazi."): "Hello, I'm glad to know you.",
    ("en", "zu", "Hello, I'm glad to know you."): "Sawubona, ngiyajabula ukukwazi.",
    ("fr", "en", "Bonjour, je suis ravi de vous rencontrer."): "Hello, I'm delighted to meet you.",
    ("en", "fr", "Hello, I'm delighted to meet you."): "Bonjour, je suis ravi de vous rencontrer.",
}

# Very rough script-based guesses, good enough for a dev mock's
# detect_language — never used once a real provider is configured.
_SCRIPT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"[一-鿿]"), "zh"),
    (re.compile(r"[؀-ۿ]"), "ar"),
    (re.compile(r"[぀-ヿ]"), "ja"),
    (re.compile(r"[가-힯]"), "ko"),
    (re.compile(r"[Ѐ-ӿ]"), "ru"),
]


class MockTranslationProvider(TranslationProvider):
    async def translate(
        self, *, text: str, source_language: str | None, target_language: str
    ) -> TranslationResult:
        resolved_source = source_language or await self.detect_language(text=text)
        known = _KNOWN_PHRASES.get((resolved_source, target_language, text.strip()))
        translated = known if known is not None else f"[{target_language} mock] {text}"
        return TranslationResult(
            original_text=text,
            translated_text=translated,
            source_language=resolved_source,
            target_language=target_language,
            provider=PROVIDER_NAME,
            status="completed",
        )

    async def detect_language(self, *, text: str) -> str:
        for pattern, language in _SCRIPT_PATTERNS:
            if pattern.search(text):
                return language
        return "en"
