import uuid
from datetime import UTC, date, datetime

from sqlalchemy import func, select

from app.models.translation import (
    ConferenceLanguagePreference,
    InterpreterSession,
    TranslationRequest,
    TranslationUsage,
    UserLanguagePreference,
    VipMessage,
    VipMessageTranslation,
)
from app.repositories.base import Repository


class UserLanguagePreferenceRepository(Repository[UserLanguagePreference]):
    model = UserLanguagePreference

    async def upsert(
        self,
        *,
        user_id: uuid.UUID,
        preferred_language: str,
        auto_detect_language: bool,
        translate_incoming: bool,
        translate_outgoing: bool,
    ) -> UserLanguagePreference:
        existing = await self.get(user_id)
        if existing is not None:
            existing.preferred_language = preferred_language
            existing.auto_detect_language = auto_detect_language
            existing.translate_incoming = translate_incoming
            existing.translate_outgoing = translate_outgoing
            existing.updated_at = datetime.now(UTC)
            await self.session.flush()
            return existing
        return await self.add(
            UserLanguagePreference(
                user_id=user_id,
                preferred_language=preferred_language,
                auto_detect_language=auto_detect_language,
                translate_incoming=translate_incoming,
                translate_outgoing=translate_outgoing,
            )
        )


class VipMessageRepository(Repository[VipMessage]):
    model = VipMessage

    async def get_by_client_message_id(self, client_message_id: str) -> VipMessage | None:
        result = await self.session.execute(
            self._select().where(VipMessage.client_message_id == client_message_id)
        )
        return result.scalar_one_or_none()

    async def list_for_conversation(self, conversation_id: uuid.UUID) -> list[VipMessage]:
        result = await self.session.execute(
            self._select()
            .where(VipMessage.conversation_id == conversation_id)
            .order_by(VipMessage.created_at.asc())
        )
        return list(result.scalars().all())


class VipMessageTranslationRepository(Repository[VipMessageTranslation]):
    model = VipMessageTranslation

    async def list_for_messages(
        self, vip_message_ids: list[uuid.UUID]
    ) -> list[VipMessageTranslation]:
        if not vip_message_ids:
            return []
        result = await self.session.execute(
            self._select().where(VipMessageTranslation.vip_message_id.in_(vip_message_ids))
        )
        return list(result.scalars().all())

    async def list_for_message(self, vip_message_id: uuid.UUID) -> list[VipMessageTranslation]:
        result = await self.session.execute(
            self._select().where(VipMessageTranslation.vip_message_id == vip_message_id)
        )
        return list(result.scalars().all())


class TranslationRequestRepository(Repository[TranslationRequest]):
    model = TranslationRequest

    async def list_for_context(
        self, *, context_type: str, context_id: uuid.UUID
    ) -> list[TranslationRequest]:
        result = await self.session.execute(
            self._select()
            .where(
                TranslationRequest.context_type == context_type,
                TranslationRequest.context_id == context_id,
            )
            .order_by(TranslationRequest.created_at.asc())
        )
        return list(result.scalars().all())

    async def count_by_status(self) -> dict[str, int]:
        result = await self.session.execute(
            select(TranslationRequest.status, func.count()).group_by(TranslationRequest.status)
        )
        return {status: count for status, count in result.all()}

    async def count_by_provider(self) -> dict[str, int]:
        result = await self.session.execute(
            select(TranslationRequest.provider, func.count())
            .where(TranslationRequest.provider.is_not(None))
            .group_by(TranslationRequest.provider)
        )
        return {provider: count for provider, count in result.all()}

    async def top_target_languages(self, limit: int = 10) -> list[tuple[str, int]]:
        result = await self.session.execute(
            select(TranslationRequest.target_language, func.count())
            .group_by(TranslationRequest.target_language)
            .order_by(func.count().desc())
            .limit(limit)
        )
        return [(target_language, count) for target_language, count in result.all()]


class InterpreterSessionRepository(Repository[InterpreterSession]):
    model = InterpreterSession

    async def list_for_user(self, user_id: uuid.UUID, limit: int = 20) -> list[InterpreterSession]:
        result = await self.session.execute(
            self._select()
            .where(InterpreterSession.user_id == user_id)
            .order_by(InterpreterSession.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


class ConferenceLanguagePreferenceRepository(Repository[ConferenceLanguagePreference]):
    model = ConferenceLanguagePreference

    async def get_by_participant(
        self, participant_id: uuid.UUID
    ) -> ConferenceLanguagePreference | None:
        result = await self.session.execute(
            self._select().where(ConferenceLanguagePreference.participant_id == participant_id)
        )
        return result.scalar_one_or_none()

    async def list_for_meeting(self, meeting_id: uuid.UUID) -> list[ConferenceLanguagePreference]:
        result = await self.session.execute(
            self._select().where(ConferenceLanguagePreference.meeting_id == meeting_id)
        )
        return list(result.scalars().all())

    async def upsert(
        self, *, meeting_id: uuid.UUID, participant_id: uuid.UUID, language: str
    ) -> ConferenceLanguagePreference:
        existing = await self.get_by_participant(participant_id)
        if existing is not None:
            existing.language = language
            await self.session.flush()
            return existing
        return await self.add(
            ConferenceLanguagePreference(
                meeting_id=meeting_id, participant_id=participant_id, language=language
            )
        )


class TranslationUsageRepository(Repository[TranslationUsage]):
    model = TranslationUsage

    async def increment(
        self, *, user_id: uuid.UUID, usage_date: date, characters: int
    ) -> TranslationUsage:
        result = await self.session.execute(
            self._select().where(
                TranslationUsage.user_id == user_id, TranslationUsage.usage_date == usage_date
            )
        )
        row = result.scalar_one_or_none()
        if row is not None:
            row.request_count += 1
            row.character_count += characters
            await self.session.flush()
            return row
        return await self.add(
            TranslationUsage(
                user_id=user_id,
                usage_date=usage_date,
                request_count=1,
                character_count=characters,
            )
        )

    async def totals_since(self, since: date) -> tuple[int, int]:
        result = await self.session.execute(
            select(func.coalesce(func.sum(TranslationUsage.request_count), 0),
                   func.coalesce(func.sum(TranslationUsage.character_count), 0))
            .where(TranslationUsage.usage_date >= since)
        )
        row = result.one()
        return int(row[0]), int(row[1])

    async def totals_for_user(self, user_id: uuid.UUID) -> tuple[int, int]:
        result = await self.session.execute(
            select(func.coalesce(func.sum(TranslationUsage.request_count), 0),
                   func.coalesce(func.sum(TranslationUsage.character_count), 0))
            .where(TranslationUsage.user_id == user_id)
        )
        row = result.one()
        return int(row[0]), int(row[1])
