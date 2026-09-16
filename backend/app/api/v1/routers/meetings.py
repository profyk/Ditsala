import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.v1.deps import CurrentUserDep, MeetingServiceDep
from app.domain.meetings.service import MeetingError
from app.schemas.meetings import (
    CreateMeetingRequest,
    GuestJoinMeetingRequest,
    JoinMeetingRequest,
    JoinMeetingResponse,
    MeetingResponse,
    RoomAccessTokenResponse,
)

router = APIRouter(prefix="/meetings", tags=["meetings"])


def _as_http_error(exc: MeetingError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.post("", response_model=MeetingResponse, status_code=201)
async def create_meeting(
    body: CreateMeetingRequest, user: CurrentUserDep, service: MeetingServiceDep
) -> MeetingResponse:
    meeting = await service.create_meeting(
        host=user,
        title=body.title,
        meeting_type=body.meeting_type,
        scheduled_start_at=body.scheduled_start_at,
        scheduled_duration_minutes=body.scheduled_duration_minutes,
        password=body.password,
        waiting_room_enabled=body.waiting_room_enabled,
    )
    return MeetingResponse.model_validate(meeting)


@router.get("/{meeting_id}", response_model=MeetingResponse)
async def get_meeting(
    meeting_id: uuid.UUID, _user: CurrentUserDep, service: MeetingServiceDep
) -> MeetingResponse:
    try:
        meeting = await service.get_meeting(meeting_id)
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return MeetingResponse.model_validate(meeting)


@router.post("/{meeting_id}/join", response_model=JoinMeetingResponse)
async def join_meeting(
    meeting_id: uuid.UUID,
    body: JoinMeetingRequest,
    user: CurrentUserDep,
    service: MeetingServiceDep,
) -> JoinMeetingResponse:
    try:
        result = await service.join(meeting_id=meeting_id, user=user, password=body.password)
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return JoinMeetingResponse(
        meeting=MeetingResponse.model_validate(result.meeting),
        participant_id=result.participant.id,
        role=result.participant.role,
        access=RoomAccessTokenResponse(
            token=result.access_token.token, livekit_url=result.access_token.livekit_url
        ),
    )


@router.post("/{meeting_id}/guest-join", response_model=JoinMeetingResponse)
async def guest_join_meeting(
    meeting_id: uuid.UUID, body: GuestJoinMeetingRequest, service: MeetingServiceDep
) -> JoinMeetingResponse:
    """§35 — deliberately no CurrentUserDep: a guest has no DITSALA account."""
    try:
        result = await service.guest_join(
            meeting_id=meeting_id,
            guest_display_name=body.guest_display_name,
            password=body.password,
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return JoinMeetingResponse(
        meeting=MeetingResponse.model_validate(result.meeting),
        participant_id=result.participant.id,
        role=result.participant.role,
        access=RoomAccessTokenResponse(
            token=result.access_token.token, livekit_url=result.access_token.livekit_url
        ),
    )


@router.post("/{meeting_id}/leave", status_code=204)
async def leave_meeting(
    meeting_id: uuid.UUID, user: CurrentUserDep, service: MeetingServiceDep
) -> None:
    await service.leave(meeting_id=meeting_id, user_id=user.id)


@router.post("/{meeting_id}/end", response_model=MeetingResponse)
async def end_meeting(
    meeting_id: uuid.UUID, user: CurrentUserDep, service: MeetingServiceDep
) -> MeetingResponse:
    try:
        meeting = await service.end_meeting(meeting_id=meeting_id, acting_user_id=user.id)
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return MeetingResponse.model_validate(meeting)
