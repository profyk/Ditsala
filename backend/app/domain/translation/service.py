"""
Ditsala VIP — TranslationService is the one place every caller (VIP chat,
the AI Interpreter, on-demand conference-chat translation) goes through,
so retry/status/usage-tracking logic lives in exactly one place rather
than being duplicated per caller (docs/DITSALA_VIP_SPEC.md).
"""

import uuid
from datetime import UTC, datetime

from app.domain.translation.interfaces import TranslationProvider
from app.models.accounts import User
from app.models.translation import InterpreterSession, TranslationRequest, UserLanguagePreference
from app.repositories.admin import SystemConfigRepository
from app.repositories.translation import (
    InterpreterSessionRepository,
    TranslationRequestRepository,
    TranslationUsageRepository,
    UserLanguagePreferenceRepository,
)

DEFAULT_SUPPORTED_LANGUAGES = [
    {"code": "en", "name": "English"},
    {"code": "zu", "name": "Zulu"},
    {"code": "tn", "name": "Setswana"},
    {"code": "fr", "name": "French"},
    {"code": "es", "name": "Spanish"},
    {"code": "zh", "name": "Chinese"},
    {"code": "pt", "name": "Portuguese"},
    {"code": "af", "name": "Afrikaans"},
]


class TranslationError(Exception):
    pass


class TranslationService:
    def __init__(
        self,
        *,
        translation_requests: TranslationRequestRepository,
        translation_usage: TranslationUsageRepository,
        user_language_preferences: UserLanguagePreferenceRepository,
        interpreter_sessions: InterpreterSessionRepository,
        system_config: SystemConfigRepository,
        provider: TranslationProvider,
    ) -> None:
        self._requests = translation_requests
        self._usage = translation_usage
        self._preferences = user_language_preferences
        self._interpreter_sessions = interpreter_sessions
        self._system_config = system_config
        self._provider = provider

    # --- entitlement + feature flags -----------------------------------

    def require_vip(self, user: User) -> None:
        """Server-side only (item 20) — a modified frontend can never grant
        this. Every VIP chat/interpreter/translation endpoint calls this
        before doing anything else."""
        if user.account_tier != "vip":
            raise TranslationError("This feature requires Ditsala VIP.")

    async def _flag_enabled(self, key: str, *, default: bool) -> bool:
        config = await self._system_config.get_by_key(key)
        if config is None:
            return default
        return bool(config.value.get("enabled", default))

    async def is_vip_enabled(self) -> bool:
        return await self._flag_enabled("vip_enabled", default=True)

    async def is_ai_translation_enabled(self) -> bool:
        return await self._flag_enabled("ai_translation_enabled", default=True)

    async def is_voice_interpretation_enabled(self) -> bool:
        # Stays false by default — no STT/TTS provider exists yet (item 7's
        # FUTURE line), so there's nothing this flag could safely turn on.
        return await self._flag_enabled("voice_interpretation_enabled", default=False)

    async def is_conference_interpretation_enabled(self) -> bool:
        return await self._flag_enabled("conference_interpretation_enabled", default=True)

    async def get_supported_languages(self) -> list[dict[str, str]]:
        config = await self._system_config.get_by_key("supported_languages")
        if config is None or not config.value.get("languages"):
            return DEFAULT_SUPPORTED_LANGUAGES
        return list(config.value["languages"])

    async def require_ai_translation_available(self) -> None:
        if not await self.is_vip_enabled():
            raise TranslationError("Ditsala VIP is not currently available.")
        if not await self.is_ai_translation_enabled():
            raise TranslationError("AI translation is not currently available.")

    # --- language preferences -------------------------------------------

    async def get_language_preferences(self, user_id: uuid.UUID) -> UserLanguagePreference | None:
        return await self._preferences.get(user_id)

    async def set_language_preferences(
        self,
        *,
        user_id: uuid.UUID,
        preferred_language: str,
        auto_detect_language: bool,
        translate_incoming: bool,
        translate_outgoing: bool,
    ) -> UserLanguagePreference:
        return await self._preferences.upsert(
            user_id=user_id,
            preferred_language=preferred_language,
            auto_detect_language=auto_detect_language,
            translate_incoming=translate_incoming,
            translate_outgoing=translate_outgoing,
        )

    # --- the one translation entry point every caller uses --------------

    async def translate_and_record(
        self,
        *,
        requested_by_user_id: uuid.UUID,
        context_type: str,
        context_id: uuid.UUID | None,
        source_text: str,
        source_language: str | None,
        target_language: str,
    ) -> TranslationRequest:
        """Writes a `pending` row, calls the provider, updates it to
        `completed`/`failed`, bumps `translation_usage`. Never raises on a
        provider failure — the row's own `status`/`error_message` carries
        that, so callers can always show "Translation unavailable... send
        the original instead" rather than losing the message (item 14)."""
        request = await self._requests.add(
            TranslationRequest(
                requested_by_user_id=requested_by_user_id,
                context_type=context_type,
                context_id=context_id,
                source_text=source_text,
                source_language=source_language,
                target_language=target_language,
                status="processing",
            )
        )
        try:
            result = await self._provider.translate(
                text=source_text, source_language=source_language, target_language=target_language
            )
        except Exception as exc:  # a provider must never take the caller down with it
            request.status = "failed"
            request.error_message = str(exc)
            request.completed_at = datetime.now(UTC)
            return request

        request.status = result.status
        request.translated_text = result.translated_text or None
        request.source_language = result.source_language
        request.provider = result.provider
        request.error_message = result.error_message
        request.completed_at = datetime.now(UTC)

        if result.status == "completed":
            await self._usage.increment(
                user_id=requested_by_user_id,
                usage_date=datetime.now(UTC).date(),
                characters=len(source_text),
            )
        return request

    async def usage_totals_for_user(self, user_id: uuid.UUID) -> tuple[int, int]:
        return await self._usage.totals_for_user(user_id)

    # --- AI Interpreter sessions (item 6) --------------------------------

    async def create_interpreter_session(
        self, *, user_id: uuid.UUID, my_language: str, other_language: str
    ) -> InterpreterSession:
        return await self._interpreter_sessions.add(
            InterpreterSession(
                user_id=user_id, my_language=my_language, other_language=other_language
            )
        )

    async def get_interpreter_session(self, session_id: uuid.UUID) -> InterpreterSession | None:
        return await self._interpreter_sessions.get(session_id)

    async def list_interpreter_sessions(self, user_id: uuid.UUID) -> list[InterpreterSession]:
        return await self._interpreter_sessions.list_for_user(user_id)

    async def list_interpreter_turns(self, session_id: uuid.UUID) -> list[TranslationRequest]:
        return await self._requests.list_for_context(
            context_type="interpreter", context_id=session_id
        )
