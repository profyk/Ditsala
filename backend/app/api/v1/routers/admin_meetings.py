import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.v1.admin_deps import (
    AdminMeetingGovernanceServiceDep,
    CurrentAdminDep,
    require_permission,
)
from app.domain.admin.meetings_governance import MeetingGovernanceError
from app.domain.admin.rbac import Permission
from app.models.meetings import Meeting
from app.schemas.admin_meetings import (
    AdminEndMeetingRequest,
    AdminExtendMeetingRequest,
    AdminMeetingAnalyticsResponse,
    AdminMeetingParticipantResponse,
    AdminMeetingResponse,
)

router = APIRouter(
    prefix="/admin/meetings",
    tags=["admin-meetings"],
    dependencies=[require_permission(Permission.MEETINGS_GOVERNANCE_VIEW)],
)


def _as_http_error(exc: MeetingGovernanceError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


def _meeting_response(meeting: Meeting, *, active_participant_count: int) -> AdminMeetingResponse:
    return AdminMeetingResponse(
        id=meeting.id,
        host_user_id=meeting.host_user_id,
        title=meeting.title,
        meeting_type=meeting.meeting_type,
        status=meeting.status,
        scheduled_start_at=meeting.scheduled_start_at,
        scheduled_duration_minutes=meeting.scheduled_duration_minutes,
        actual_start_at=meeting.actual_start_at,
        duration_extended_minutes=meeting.duration_extended_minutes,
        max_participants=meeting.max_participants,
        waiting_room_enabled=meeting.waiting_room_enabled,
        locked_at=meeting.locked_at,
        active_participant_count=active_participant_count,
    )


async def _active_count(service: AdminMeetingGovernanceServiceDep, meeting_id: uuid.UUID) -> int:
    participants = await service.list_participants(meeting_id)
    return sum(1 for p in participants if p.left_at is None and p.joined_at is not None)


@router.get("", response_model=list[AdminMeetingResponse])
async def list_meetings(service: AdminMeetingGovernanceServiceDep) -> list[AdminMeetingResponse]:
    """Every live or scheduled meeting platform-wide — the admin
    equivalent of `GET /meetings`, which is scoped to "meetings I host."
    See `AdminMeetingGovernanceService`'s docstring for why this is new."""
    items = await service.list_live_and_scheduled()
    return [
        _meeting_response(item.meeting, active_participant_count=item.active_participant_count)
        for item in items
    ]


@router.get("/{meeting_id}/participants", response_model=list[AdminMeetingParticipantResponse])
async def list_participants(
    meeting_id: uuid.UUID, service: AdminMeetingGovernanceServiceDep
) -> list[AdminMeetingParticipantResponse]:
    try:
        participants = await service.list_participants(meeting_id)
    except MeetingGovernanceError as exc:
        raise _as_http_error(exc) from exc
    return [AdminMeetingParticipantResponse.model_validate(p) for p in participants]


@router.get("/{meeting_id}/analytics", response_model=AdminMeetingAnalyticsResponse)
async def get_analytics(
    meeting_id: uuid.UUID, service: AdminMeetingGovernanceServiceDep
) -> AdminMeetingAnalyticsResponse:
    """Unlike the host-facing `GET /meetings/{id}/analytics`, this is
    never plan-gated — an admin isn't subject to the host's own
    Conference plan entitlements."""
    try:
        report = await service.get_analytics(meeting_id)
    except MeetingGovernanceError as exc:
        raise _as_http_error(exc) from exc
    return AdminMeetingAnalyticsResponse.model_validate(report)


@router.post(
    "/{meeting_id}/extend",
    response_model=AdminMeetingResponse,
    dependencies=[require_permission(Permission.MEETINGS_GOVERNANCE_ACTION)],
)
async def extend_meeting(
    meeting_id: uuid.UUID,
    body: AdminExtendMeetingRequest,
    admin: CurrentAdminDep,
    service: AdminMeetingGovernanceServiceDep,
) -> AdminMeetingResponse:
    try:
        meeting = await service.extend_meeting(
            admin_id=admin.id,
            meeting_id=meeting_id,
            additional_minutes=body.additional_minutes,
            reason=body.reason,
        )
    except MeetingGovernanceError as exc:
        raise _as_http_error(exc) from exc
    return _meeting_response(
        meeting, active_participant_count=await _active_count(service, meeting_id)
    )


@router.post(
    "/{meeting_id}/end",
    response_model=AdminMeetingResponse,
    dependencies=[require_permission(Permission.MEETINGS_GOVERNANCE_ACTION)],
)
async def end_meeting(
    meeting_id: uuid.UUID,
    body: AdminEndMeetingRequest,
    admin: CurrentAdminDep,
    service: AdminMeetingGovernanceServiceDep,
) -> AdminMeetingResponse:
    try:
        meeting = await service.end_meeting(
            admin_id=admin.id, meeting_id=meeting_id, reason=body.reason
        )
    except MeetingGovernanceError as exc:
        raise _as_http_error(exc) from exc
    return _meeting_response(
        meeting, active_participant_count=await _active_count(service, meeting_id)
    )
