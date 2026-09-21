import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.v1.deps import CurrentUserDep, TranslationServiceDep
from app.domain.translation.service import TranslationError
from app.schemas.translation import (
    CreateInterpreterSessionRequest,
    InterpreterSessionResponse,
    InterpreterTranslateRequest,
    LanguagePreferencesResponse,
    LanguageResponse,
    SetLanguagePreferencesRequest,
    TranslationResultResponse,
    VipUsageResponse,
)

router = APIRouter(prefix="/vip", tags=["vip"])


def _as_http_error(exc: TranslationError) -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))


@router.get("/languages", response_model=list[LanguageResponse])
async def list_languages(
    user: CurrentUserDep, service: TranslationServiceDep
) -> list[LanguageResponse]:
    """Not VIP-gated — a normal-tier user should still see what VIP
    unlocks (item 10's "tasteful upgrade screen" needs this list too)."""
    languages = await service.get_supported_languages()
    return [LanguageResponse(**lang) for lang in languages]


@router.get("/language-preferences", response_model=LanguagePreferencesResponse)
async def get_language_preferences(
    user: CurrentUserDep, service: TranslationServiceDep
) -> LanguagePreferencesResponse:
    try:
        service.require_vip(user)
    except TranslationError as exc:
        raise _as_http_error(exc) from exc
    prefs = await service.get_language_preferences(user.id)
    if prefs is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No language preferences set yet.")
    return LanguagePreferencesResponse.model_validate(prefs)


@router.put("/language-preferences", response_model=LanguagePreferencesResponse)
async def set_language_preferences(
    body: SetLanguagePreferencesRequest, user: CurrentUserDep, service: TranslationServiceDep
) -> LanguagePreferencesResponse:
    try:
        service.require_vip(user)
    except TranslationError as exc:
        raise _as_http_error(exc) from exc
    prefs = await service.set_language_preferences(
        user_id=user.id,
        preferred_language=body.preferred_language,
        auto_detect_language=body.auto_detect_language,
        translate_incoming=body.translate_incoming,
        translate_outgoing=body.translate_outgoing,
    )
    return LanguagePreferencesResponse.model_validate(prefs)


@router.get("/usage/me", response_model=VipUsageResponse)
async def get_my_usage(user: CurrentUserDep, service: TranslationServiceDep) -> VipUsageResponse:
    try:
        service.require_vip(user)
    except TranslationError as exc:
        raise _as_http_error(exc) from exc
    request_count, character_count = await service.usage_totals_for_user(user.id)
    return VipUsageResponse(request_count=request_count, character_count=character_count)


# ---- AI Interpreter (item 6) ------------------------------------------------


@router.post(
    "/interpreter/sessions", response_model=InterpreterSessionResponse, status_code=201
)
async def create_interpreter_session(
    body: CreateInterpreterSessionRequest, user: CurrentUserDep, service: TranslationServiceDep
) -> InterpreterSessionResponse:
    try:
        service.require_vip(user)
        await service.require_ai_translation_available()
    except TranslationError as exc:
        raise _as_http_error(exc) from exc
    session = await service.create_interpreter_session(
        user_id=user.id, my_language=body.my_language, other_language=body.other_language
    )
    return InterpreterSessionResponse.model_validate(session)


@router.post(
    "/interpreter/sessions/{session_id}/translate", response_model=TranslationResultResponse
)
async def interpreter_translate(
    session_id: uuid.UUID,
    body: InterpreterTranslateRequest,
    user: CurrentUserDep,
    service: TranslationServiceDep,
) -> TranslationResultResponse:
    try:
        service.require_vip(user)
        await service.require_ai_translation_available()
    except TranslationError as exc:
        raise _as_http_error(exc) from exc
    session = await service.get_interpreter_session(session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such interpreter session.")
    source_lang, target_lang = (
        (session.my_language, session.other_language)
        if body.direction == "forward"
        else (session.other_language, session.my_language)
    )
    request = await service.translate_and_record(
        requested_by_user_id=user.id,
        context_type="interpreter",
        context_id=session.id,
        source_text=body.text,
        source_language=source_lang,
        target_language=target_lang,
    )
    return TranslationResultResponse.model_validate(request)


@router.get(
    "/interpreter/sessions/{session_id}/turns", response_model=list[TranslationResultResponse]
)
async def list_interpreter_turns(
    session_id: uuid.UUID, user: CurrentUserDep, service: TranslationServiceDep
) -> list[TranslationResultResponse]:
    try:
        service.require_vip(user)
    except TranslationError as exc:
        raise _as_http_error(exc) from exc
    session = await service.get_interpreter_session(session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such interpreter session.")
    turns = await service.list_interpreter_turns(session_id)
    return [TranslationResultResponse.model_validate(t) for t in turns]


@router.get("/interpreter/sessions", response_model=list[InterpreterSessionResponse])
async def list_interpreter_sessions(
    user: CurrentUserDep, service: TranslationServiceDep
) -> list[InterpreterSessionResponse]:
    try:
        service.require_vip(user)
    except TranslationError as exc:
        raise _as_http_error(exc) from exc
    sessions = await service.list_interpreter_sessions(user.id)
    return [InterpreterSessionResponse.model_validate(s) for s in sessions]
