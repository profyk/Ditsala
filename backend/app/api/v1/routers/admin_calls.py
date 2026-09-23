import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.v1.admin_deps import (
    AdminCallGovernanceServiceDep,
    CurrentAdminDep,
    require_permission,
)
from app.domain.admin.calls_governance import CallGovernanceError
from app.domain.admin.rbac import Permission
from app.schemas.admin_calls import AdminCallResponse, AdminEndCallRequest

router = APIRouter(
    prefix="/admin/calls",
    tags=["admin-calls"],
    dependencies=[require_permission(Permission.CALLS_GOVERNANCE_VIEW)],
)


def _as_http_error(exc: CallGovernanceError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.get("", response_model=list[AdminCallResponse])
async def list_live_calls(service: AdminCallGovernanceServiceDep) -> list[AdminCallResponse]:
    """Every ringing/active call platform-wide — the admin equivalent of
    `GET /calls`, which is scoped to "calls I'm a participant in." See
    `AdminCallGovernanceService`'s docstring for why this is new."""
    calls = await service.list_live()
    return [AdminCallResponse.model_validate(c) for c in calls]


@router.post(
    "/{call_id}/end",
    response_model=AdminCallResponse,
    dependencies=[require_permission(Permission.CALLS_GOVERNANCE_ACTION)],
)
async def end_call(
    call_id: uuid.UUID,
    body: AdminEndCallRequest,
    admin: CurrentAdminDep,
    service: AdminCallGovernanceServiceDep,
) -> AdminCallResponse:
    try:
        call = await service.end_call(admin_id=admin.id, call_id=call_id, reason=body.reason)
    except CallGovernanceError as exc:
        raise _as_http_error(exc) from exc
    return AdminCallResponse.model_validate(call)
