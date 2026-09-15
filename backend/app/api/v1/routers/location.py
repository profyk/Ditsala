import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.v1.deps import CurrentUserDep, LocationServiceDep
from app.domain.location.service import LocationError
from app.schemas.location import (
    CreateLocationShareRequest,
    LocationAccessLogResponse,
    LocationPingResponse,
    LocationShareResponse,
    RecordPingRequest,
)

router = APIRouter(prefix="/location", tags=["location"])


def _as_http_error(exc: LocationError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.post("/shares", response_model=LocationShareResponse, status_code=201)
async def create_share(
    body: CreateLocationShareRequest, user: CurrentUserDep, service: LocationServiceDep
) -> LocationShareResponse:
    try:
        share = await service.create_share(
            sharer_id=user.id,
            recipient_id=body.recipient_user_id,
            duration_seconds=body.duration_seconds,
        )
    except LocationError as exc:
        raise _as_http_error(exc) from exc
    return LocationShareResponse.model_validate(share)


@router.delete("/shares/{share_id}", status_code=204)
async def revoke_share(
    share_id: uuid.UUID, user: CurrentUserDep, service: LocationServiceDep
) -> None:
    try:
        await service.revoke_share(user_id=user.id, share_id=share_id)
    except LocationError as exc:
        raise _as_http_error(exc) from exc


@router.get("/shares/by-me", response_model=list[LocationShareResponse])
async def list_shares_by_me(
    user: CurrentUserDep, service: LocationServiceDep
) -> list[LocationShareResponse]:
    shares = await service.list_shares_by_me(user.id)
    return [LocationShareResponse.model_validate(s) for s in shares]


@router.get("/shares/to-me", response_model=list[LocationShareResponse])
async def list_shares_to_me(
    user: CurrentUserDep, service: LocationServiceDep
) -> list[LocationShareResponse]:
    shares = await service.list_shares_to_me(user.id)
    return [LocationShareResponse.model_validate(s) for s in shares]


@router.post("/shares/{share_id}/pings", response_model=LocationPingResponse, status_code=201)
async def record_ping(
    share_id: uuid.UUID,
    body: RecordPingRequest,
    user: CurrentUserDep,
    service: LocationServiceDep,
) -> LocationPingResponse:
    try:
        ping = await service.record_ping(
            sharer_id=user.id,
            share_id=share_id,
            lat=body.lat,
            lng=body.lng,
            accuracy_m=body.accuracy_m,
        )
    except LocationError as exc:
        raise _as_http_error(exc) from exc
    return LocationPingResponse.model_validate(ping)


@router.get("/shares/{share_id}/pings", response_model=list[LocationPingResponse])
async def list_pings(
    share_id: uuid.UUID, user: CurrentUserDep, service: LocationServiceDep
) -> list[LocationPingResponse]:
    try:
        pings = await service.list_pings(viewer_id=user.id, share_id=share_id)
    except LocationError as exc:
        raise _as_http_error(exc) from exc
    return [LocationPingResponse.model_validate(p) for p in pings]


@router.get(
    "/shares/{share_id}/access-log", response_model=list[LocationAccessLogResponse]
)
async def list_access_log(
    share_id: uuid.UUID, user: CurrentUserDep, service: LocationServiceDep
) -> list[LocationAccessLogResponse]:
    try:
        log = await service.list_access_log(sharer_id=user.id, share_id=share_id)
    except LocationError as exc:
        raise _as_http_error(exc) from exc
    return [LocationAccessLogResponse.model_validate(entry) for entry in log]
