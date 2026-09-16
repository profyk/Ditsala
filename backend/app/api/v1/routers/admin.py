import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.v1.admin_deps import AdminServiceDep, CurrentAdminDep, require_permission
from app.domain.admin.rbac import Permission
from app.domain.admin.service import AdminError
from app.schemas.admin import (
    ActionReportRequest,
    AuditLogEntryResponse,
    DashboardSummaryResponse,
    ForceAccountStateRequest,
    InvitationStatsResponse,
    InviteOnlyModeResponse,
    ReportResponse,
    SecuritySummaryResponse,
    SetInviteOnlyModeRequest,
    SetSystemConfigRequest,
    SystemConfigResponse,
    UserSummaryResponse,
)

router = APIRouter(prefix="/admin", tags=["admin"])


def _as_http_error(exc: AdminError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


# --- §28.1: dashboard ---


@router.get(
    "/dashboard",
    response_model=DashboardSummaryResponse,
    dependencies=[require_permission(Permission.DASHBOARD_VIEW)],
)
async def get_dashboard(service: AdminServiceDep) -> DashboardSummaryResponse:
    summary = await service.get_dashboard_summary()
    return DashboardSummaryResponse(**summary.__dict__)


# --- §28.3: users ---


@router.get(
    "/users",
    response_model=list[UserSummaryResponse],
    dependencies=[require_permission(Permission.USERS_VIEW)],
)
async def search_users(
    service: AdminServiceDep,
    q: Annotated[str | None, Query()] = None,
    account_state: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[UserSummaryResponse]:
    users = await service.search_users(
        query=q, account_state=account_state, limit=limit, offset=offset
    )
    return [UserSummaryResponse.model_validate(u) for u in users]


@router.get(
    "/users/{user_id}",
    response_model=UserSummaryResponse,
    dependencies=[require_permission(Permission.USERS_VIEW)],
)
async def get_user(user_id: uuid.UUID, service: AdminServiceDep) -> UserSummaryResponse:
    try:
        user = await service.get_user(user_id)
    except AdminError as exc:
        raise _as_http_error(exc) from exc
    return UserSummaryResponse.model_validate(user)


@router.get(
    "/users/{user_id}/history",
    response_model=list[AuditLogEntryResponse],
    dependencies=[require_permission(Permission.USERS_VIEW)],
)
async def get_user_history(
    user_id: uuid.UUID, service: AdminServiceDep
) -> list[AuditLogEntryResponse]:
    history = await service.get_user_state_history(user_id)
    return [AuditLogEntryResponse.model_validate(entry) for entry in history]


@router.post(
    "/users/{user_id}/state",
    response_model=UserSummaryResponse,
    dependencies=[require_permission(Permission.USERS_ACTION)],
)
async def force_account_state(
    user_id: uuid.UUID,
    body: ForceAccountStateRequest,
    admin: CurrentAdminDep,
    service: AdminServiceDep,
) -> UserSummaryResponse:
    try:
        user = await service.force_account_state(
            admin_id=admin.id, user_id=user_id, new_state=body.new_state, reason=body.reason
        )
    except AdminError as exc:
        raise _as_http_error(exc) from exc
    return UserSummaryResponse.model_validate(user)


# --- §28.4: reports & moderation ---


@router.get(
    "/reports",
    response_model=list[ReportResponse],
    dependencies=[require_permission(Permission.REPORTS_VIEW)],
)
async def list_reports(
    service: AdminServiceDep, status_filter: Annotated[str, Query(alias="status")] = "open"
) -> list[ReportResponse]:
    reports = await service.list_reports(status=status_filter)
    return [ReportResponse.model_validate(r) for r in reports]


@router.post(
    "/reports/{report_id}/action",
    response_model=ReportResponse,
    dependencies=[require_permission(Permission.REPORTS_ACTION)],
)
async def action_report(
    report_id: uuid.UUID,
    body: ActionReportRequest,
    admin: CurrentAdminDep,
    service: AdminServiceDep,
) -> ReportResponse:
    try:
        report = await service.action_report(
            admin_id=admin.id, report_id=report_id, action=body.action, reason=body.reason
        )
    except AdminError as exc:
        raise _as_http_error(exc) from exc
    return ReportResponse.model_validate(report)


# --- §28.5: security dashboard ---


@router.get(
    "/security",
    response_model=SecuritySummaryResponse,
    dependencies=[require_permission(Permission.SECURITY_VIEW)],
)
async def get_security_summary(service: AdminServiceDep) -> SecuritySummaryResponse:
    summary = await service.get_security_summary()
    return SecuritySummaryResponse(**summary.__dict__)


# --- §28.6: invitations ---


@router.get(
    "/invitations/invite-only-mode",
    response_model=InviteOnlyModeResponse,
    dependencies=[require_permission(Permission.INVITATIONS_VIEW)],
)
async def get_invite_only_mode(service: AdminServiceDep) -> InviteOnlyModeResponse:
    return InviteOnlyModeResponse(enabled=await service.get_invite_only_mode())


@router.post(
    "/invitations/invite-only-mode",
    status_code=204,
    dependencies=[require_permission(Permission.INVITATIONS_ACTION)],
)
async def set_invite_only_mode(
    body: SetInviteOnlyModeRequest, admin: CurrentAdminDep, service: AdminServiceDep
) -> None:
    await service.set_invite_only_mode(admin_id=admin.id, enabled=body.enabled, reason=body.reason)


@router.get(
    "/invitations/stats",
    response_model=InvitationStatsResponse,
    dependencies=[require_permission(Permission.INVITATIONS_VIEW)],
)
async def get_invitation_stats(service: AdminServiceDep) -> InvitationStatsResponse:
    stats = await service.get_invitation_stats()
    return InvitationStatsResponse(
        sent=stats.sent,
        redeemed=stats.redeemed,
        expired=stats.expired,
        top_inviters=[
            {"inviter_user_id": str(inviter_id), "sent_count": count}
            for inviter_id, count in stats.top_inviters
        ],
    )


# --- §28.7: audit log ---


@router.get(
    "/audit-log",
    response_model=list[AuditLogEntryResponse],
    dependencies=[require_permission(Permission.AUDIT_VIEW)],
)
async def list_audit_log(
    service: AdminServiceDep,
    actor_id: Annotated[uuid.UUID | None, Query()] = None,
    action: Annotated[str | None, Query()] = None,
    target_type: Annotated[str | None, Query()] = None,
    target_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditLogEntryResponse]:
    entries = await service.list_audit_log(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        limit=limit,
        offset=offset,
    )
    return [AuditLogEntryResponse.model_validate(entry) for entry in entries]


# --- §28.8: system configuration ---


@router.get(
    "/system-config",
    response_model=list[SystemConfigResponse],
    dependencies=[require_permission(Permission.SYSTEM_CONFIG_VIEW)],
)
async def list_system_config(service: AdminServiceDep) -> list[SystemConfigResponse]:
    configs = await service.list_system_config()
    return [SystemConfigResponse.model_validate(c) for c in configs]


@router.put(
    "/system-config/{key}",
    response_model=SystemConfigResponse,
    dependencies=[require_permission(Permission.SYSTEM_CONFIG_ACTION)],
)
async def set_system_config(
    key: str, body: SetSystemConfigRequest, admin: CurrentAdminDep, service: AdminServiceDep
) -> SystemConfigResponse:
    config = await service.set_system_config(
        admin_id=admin.id, key=key, value=body.value, reason=body.reason
    )
    return SystemConfigResponse.model_validate(config)
