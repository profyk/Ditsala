"""
Unit tests for TranslationService — the shared entry point VIP chat, the
AI Interpreter, and (future) conference-chat translation all go through.
Real Postgres; MockTranslationProvider is used directly since it's real
dev-only code, not a test stub, same as every other adapter this repo
exercises through its own sandbox variant.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.domain.translation.interfaces import TranslationProvider, TranslationResult
from app.domain.translation.service import (
    DEFAULT_SUPPORTED_LANGUAGES,
    TranslationError,
    TranslationService,
)
from app.models.accounts import User
from app.repositories.admin import SystemConfigRepository
from app.repositories.translation import (
    InterpreterSessionRepository,
    TranslationRequestRepository,
    TranslationUsageRepository,
    UserLanguagePreferenceRepository,
)
from app.repositories.users import UserRepository
from app.services.translation.mock import MockTranslationProvider


class FailingTranslationProvider(TranslationProvider):
    """A provider that always raises — proves translate_and_record never
    lets a provider failure take the caller down with it (item 14)."""

    async def translate(
        self, *, text: str, source_language: str | None, target_language: str
    ) -> TranslationResult:
        raise RuntimeError("provider unreachable")

    async def detect_language(self, *, text: str) -> str:
        raise RuntimeError("provider unreachable")


@dataclass
class Harness:
    service: TranslationService
    users: UserRepository
    system_config: SystemConfigRepository


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
        await s.rollback()
    await engine.dispose()


def _build_service(session: AsyncSession, provider: TranslationProvider) -> TranslationService:
    return TranslationService(
        translation_requests=TranslationRequestRepository(session),
        translation_usage=TranslationUsageRepository(session),
        user_language_preferences=UserLanguagePreferenceRepository(session),
        interpreter_sessions=InterpreterSessionRepository(session),
        system_config=SystemConfigRepository(session),
        provider=provider,
    )


@pytest.fixture
def harness(session: AsyncSession) -> Harness:
    return Harness(
        service=_build_service(session, MockTranslationProvider()),
        users=UserRepository(session),
        system_config=SystemConfigRepository(session),
    )


async def _make_user(harness: Harness, *, account_tier: str = "vip") -> User:
    return await harness.users.add(
        User(
            email=f"{uuid.uuid4()}@example.com",
            phone=f"+27{uuid.uuid4().int % 10**9}",
            display_name="Translation Test User",
            date_of_birth=datetime(1990, 1, 1),
            national_id_hash=uuid.uuid4().hex,
            account_state="active",
            account_tier=account_tier,
        )
    )


# --- entitlement ---


async def test_require_vip_rejects_normal_tier(harness: Harness) -> None:
    normal_user = await _make_user(harness, account_tier="normal")
    with pytest.raises(TranslationError, match="Ditsala VIP"):
        harness.service.require_vip(normal_user)


async def test_require_vip_allows_vip_tier(harness: Harness) -> None:
    vip_user = await _make_user(harness, account_tier="vip")
    harness.service.require_vip(vip_user)  # does not raise


async def test_get_supported_languages_defaults_when_unconfigured(harness: Harness) -> None:
    languages = await harness.service.get_supported_languages()
    assert languages == DEFAULT_SUPPORTED_LANGUAGES


# --- language preferences ---


async def test_set_and_get_language_preferences(harness: Harness) -> None:
    user = await _make_user(harness)
    saved = await harness.service.set_language_preferences(
        user_id=user.id,
        preferred_language="fr",
        auto_detect_language=True,
        translate_incoming=True,
        translate_outgoing=False,
    )
    assert saved.preferred_language == "fr"

    fetched = await harness.service.get_language_preferences(user.id)
    assert fetched is not None
    assert fetched.auto_detect_language is True
    assert fetched.translate_outgoing is False


async def test_set_language_preferences_upserts(harness: Harness) -> None:
    user = await _make_user(harness)
    await harness.service.set_language_preferences(
        user_id=user.id,
        preferred_language="fr",
        auto_detect_language=False,
        translate_incoming=True,
        translate_outgoing=True,
    )
    updated = await harness.service.set_language_preferences(
        user_id=user.id,
        preferred_language="zu",
        auto_detect_language=False,
        translate_incoming=True,
        translate_outgoing=True,
    )
    assert updated.preferred_language == "zu"
    fetched = await harness.service.get_language_preferences(user.id)
    assert fetched is not None and fetched.preferred_language == "zu"


# --- translate_and_record ---


async def test_translate_and_record_success_increments_usage(harness: Harness) -> None:
    user = await _make_user(harness)
    request = await harness.service.translate_and_record(
        requested_by_user_id=user.id,
        context_type="vip_message",
        context_id=uuid.uuid4(),
        source_text="Hello, nice to meet you.",
        source_language="en",
        target_language="zh",
    )
    assert request.status == "completed"
    assert request.translated_text == "你好，很高兴认识你。"
    assert request.provider == "mock"

    request_count, character_count = await harness.service.usage_totals_for_user(user.id)
    assert request_count == 1
    assert character_count == len("Hello, nice to meet you.")


async def test_translate_and_record_auto_detects_when_source_language_none(
    harness: Harness,
) -> None:
    user = await _make_user(harness)
    request = await harness.service.translate_and_record(
        requested_by_user_id=user.id,
        context_type="interpreter",
        context_id=uuid.uuid4(),
        source_text="你好，很高兴认识你。",
        source_language=None,
        target_language="en",
    )
    assert request.source_language == "zh"
    assert request.translated_text == "Hello, nice to meet you."


async def test_translate_and_record_never_raises_on_provider_failure(session: AsyncSession) -> None:
    service = _build_service(session, FailingTranslationProvider())
    users = UserRepository(session)
    user = await users.add(
        User(
            email=f"{uuid.uuid4()}@example.com",
            phone=f"+27{uuid.uuid4().int % 10**9}",
            display_name="Translation Test User",
            date_of_birth=datetime(1990, 1, 1),
            national_id_hash=uuid.uuid4().hex,
            account_state="active",
            account_tier="vip",
        )
    )
    request = await service.translate_and_record(
        requested_by_user_id=user.id,
        context_type="vip_message",
        context_id=uuid.uuid4(),
        source_text="This will fail.",
        source_language="en",
        target_language="fr",
    )
    assert request.status == "failed"
    assert request.error_message == "provider unreachable"

    # A failed translation must never be counted as usage.
    request_count, character_count = await service.usage_totals_for_user(user.id)
    assert request_count == 0
    assert character_count == 0


# --- AI Interpreter sessions ---


async def test_interpreter_session_lifecycle(harness: Harness) -> None:
    user = await _make_user(harness)
    session_obj = await harness.service.create_interpreter_session(
        user_id=user.id, my_language="en", other_language="zu"
    )
    assert session_obj.my_language == "en"

    fetched = await harness.service.get_interpreter_session(session_obj.id)
    assert fetched is not None and fetched.id == session_obj.id

    sessions = await harness.service.list_interpreter_sessions(user.id)
    assert [s.id for s in sessions] == [session_obj.id]

    await harness.service.translate_and_record(
        requested_by_user_id=user.id,
        context_type="interpreter",
        context_id=session_obj.id,
        source_text="Hello, I'm glad to know you.",
        source_language="en",
        target_language="zu",
    )
    turns = await harness.service.list_interpreter_turns(session_obj.id)
    assert len(turns) == 1
    assert turns[0].translated_text == "Sawubona, ngiyajabula ukukwazi."
