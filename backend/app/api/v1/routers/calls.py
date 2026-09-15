import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.v1.deps import CallServiceDep, CurrentUserDep, SettingsDep
from app.domain.calls.service import CallError
from app.schemas.calls import (
    CallResponse,
    CallSignalRequest,
    IceServer,
    IceServersResponse,
    InitiateCallRequest,
    SwitchMediaRequest,
)

router = APIRouter(prefix="/calls", tags=["calls"])


def _as_http_error(exc: CallError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.get("/ice-servers", response_model=IceServersResponse)
async def get_ice_servers(_user: CurrentUserDep, settings: SettingsDep) -> IceServersResponse:
    """§27: STUN (public, no credentials) + the self-hosted coturn TURN
    server (infra/docker-compose.yml) — TURN relay only, media itself is
    peer-to-peer DTLS-SRTP end-to-end."""
    return IceServersResponse(
        ice_servers=[
            IceServer(urls=settings.stun_url),
            IceServer(
                urls=settings.turn_url,
                username=settings.turn_username,
                credential=settings.turn_credential,
            ),
        ]
    )


@router.post("", response_model=CallResponse, status_code=201)
async def initiate_call(
    body: InitiateCallRequest, user: CurrentUserDep, service: CallServiceDep
) -> CallResponse:
    try:
        call = await service.initiate_call(
            initiator_id=user.id,
            conversation_id=body.conversation_id,
            call_type=body.call_type,
        )
    except CallError as exc:
        raise _as_http_error(exc) from exc
    return CallResponse.model_validate(call)


@router.post("/{call_id}/answer", response_model=CallResponse)
async def answer_call(
    call_id: uuid.UUID, user: CurrentUserDep, service: CallServiceDep
) -> CallResponse:
    try:
        call = await service.answer_call(call_id=call_id, user_id=user.id)
    except CallError as exc:
        raise _as_http_error(exc) from exc
    return CallResponse.model_validate(call)


@router.post("/{call_id}/decline", response_model=CallResponse)
async def decline_call(
    call_id: uuid.UUID, user: CurrentUserDep, service: CallServiceDep
) -> CallResponse:
    try:
        call = await service.decline_call(call_id=call_id, user_id=user.id)
    except CallError as exc:
        raise _as_http_error(exc) from exc
    return CallResponse.model_validate(call)


@router.post("/{call_id}/end", response_model=CallResponse)
async def end_call(
    call_id: uuid.UUID, user: CurrentUserDep, service: CallServiceDep
) -> CallResponse:
    try:
        call = await service.end_call(call_id=call_id, user_id=user.id)
    except CallError as exc:
        raise _as_http_error(exc) from exc
    return CallResponse.model_validate(call)


@router.post("/{call_id}/switch-media", response_model=CallResponse)
async def switch_media(
    call_id: uuid.UUID, body: SwitchMediaRequest, user: CurrentUserDep, service: CallServiceDep
) -> CallResponse:
    """§27: switch a live call between voice and video at any time."""
    try:
        call = await service.switch_media(
            call_id=call_id, user_id=user.id, call_type=body.call_type
        )
    except CallError as exc:
        raise _as_http_error(exc) from exc
    return CallResponse.model_validate(call)


@router.post("/{call_id}/signal", status_code=204)
async def send_signal(
    call_id: uuid.UUID, body: CallSignalRequest, user: CurrentUserDep, service: CallServiceDep
) -> None:
    try:
        await service.relay_signal(call_id=call_id, from_user_id=user.id, payload=body.payload)
    except CallError as exc:
        raise _as_http_error(exc) from exc


@router.get("", response_model=list[CallResponse])
async def list_calls(user: CurrentUserDep, service: CallServiceDep) -> list[CallResponse]:
    calls = await service.list_calls(user.id)
    return [CallResponse.model_validate(c) for c in calls]
