import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.v1.deps import CurrentUserDep, SosServiceDep
from app.domain.sos.service import SosError
from app.schemas.sos import SosEventResponse, SosNotificationResponse, TriggerSosRequest

router = APIRouter(prefix="/sos", tags=["sos"])


def _as_http_error(exc: SosError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.post("/trigger", response_model=SosEventResponse, status_code=201)
async def trigger_sos(
    body: TriggerSosRequest, user: CurrentUserDep, service: SosServiceDep
) -> SosEventResponse:
    event = await service.trigger(
        user_id=user.id, last_known_location_ref=body.last_known_location_ref
    )
    return SosEventResponse.model_validate(event)


@router.post("/{event_id}/cancel", response_model=SosEventResponse)
async def cancel_sos(
    event_id: uuid.UUID, user: CurrentUserDep, service: SosServiceDep
) -> SosEventResponse:
    try:
        event = await service.cancel(user_id=user.id, event_id=event_id)
    except SosError as exc:
        raise _as_http_error(exc) from exc
    return SosEventResponse.model_validate(event)


@router.post("/{event_id}/escalate", response_model=SosEventResponse)
async def escalate_sos(
    event_id: uuid.UUID, _user: CurrentUserDep, service: SosServiceDep
) -> SosEventResponse:
    """
    Real escalation logic, invoked here for now rather than by a scheduler
    — Phase 8 wires the actual background job that calls this once the
    cancel window elapses (same deferred-scheduling note as
    `MessagingService.purge_expired_messages`). Any authenticated user can
    call this; `SosService.escalate` itself enforces the window/state
    checks, so nothing sensitive hinges on who calls it early.
    """
    try:
        event = await service.escalate(event_id=event_id)
    except SosError as exc:
        raise _as_http_error(exc) from exc
    return SosEventResponse.model_validate(event)


@router.get("", response_model=list[SosEventResponse])
async def list_sos_events(
    user: CurrentUserDep, service: SosServiceDep
) -> list[SosEventResponse]:
    events = await service.list_for_user(user.id)
    return [SosEventResponse.model_validate(e) for e in events]


@router.get("/{event_id}/notifications", response_model=list[SosNotificationResponse])
async def list_sos_notifications(
    event_id: uuid.UUID, user: CurrentUserDep, service: SosServiceDep
) -> list[SosNotificationResponse]:
    try:
        notifications = await service.list_notifications(user_id=user.id, event_id=event_id)
    except SosError as exc:
        raise _as_http_error(exc) from exc
    return [SosNotificationResponse.model_validate(n) for n in notifications]
