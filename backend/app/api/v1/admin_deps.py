"""
Admin-panel dependencies — split from `deps.py` given Phase 7's size, not
a different pattern: `SessionDep`/`SettingsDep` are reused from there.
"""

from typing import Annotated, Any

import jwt
from fastapi import Depends, Header, HTTPException, status

from app.api.v1.deps import SessionDep, SettingsDep
from app.core.security import decode_admin_access_token
from app.domain.admin.auth_service import AdminAuthService
from app.domain.admin.kyc_review_service import KycReviewService
from app.domain.admin.rbac import Permission
from app.domain.admin.service import AdminService
from app.domain.billing.plans import PlanService
from app.models.admin import AdminUser
from app.repositories.admin import (
    AdminRoleRepository,
    AdminUserRepository,
    AuditLogRepository,
    SystemConfigRepository,
)
from app.repositories.billing import EntitlementRepository, PlanPriceRepository, PlanRepository
from app.repositories.circle import InvitationRepository, ReportRepository
from app.repositories.devices import DeviceRepository, LoginAttemptRepository, SessionRepository
from app.repositories.kyc import KycDocumentRepository, KycFaceVerificationRepository
from app.repositories.users import UserRepository


async def get_admin_auth_service(session: SessionDep, settings: SettingsDep) -> AdminAuthService:
    return AdminAuthService(
        admin_users=AdminUserRepository(session),
        admin_roles=AdminRoleRepository(session),
        audit_log=AuditLogRepository(session),
        jwt_secret=settings.jwt_secret,
        access_token_ttl_minutes=settings.admin_access_token_ttl_minutes,
    )


AdminAuthServiceDep = Annotated[AdminAuthService, Depends(get_admin_auth_service)]


async def get_admin_service(session: SessionDep) -> AdminService:
    return AdminService(
        users=UserRepository(session),
        reports=ReportRepository(session),
        invitations=InvitationRepository(session),
        devices=DeviceRepository(session),
        sessions=SessionRepository(session),
        login_attempts=LoginAttemptRepository(session),
        system_config=SystemConfigRepository(session),
        audit_log=AuditLogRepository(session),
        admin_users=AdminUserRepository(session),
        admin_roles=AdminRoleRepository(session),
    )


AdminServiceDep = Annotated[AdminService, Depends(get_admin_service)]


async def get_kyc_review_service(session: SessionDep) -> KycReviewService:
    return KycReviewService(
        users=UserRepository(session),
        kyc_documents=KycDocumentRepository(session),
        kyc_face_verifications=KycFaceVerificationRepository(session),
        audit_log=AuditLogRepository(session),
    )


KycReviewServiceDep = Annotated[KycReviewService, Depends(get_kyc_review_service)]


async def get_plan_service(session: SessionDep) -> PlanService:
    return PlanService(
        plans=PlanRepository(session),
        plan_prices=PlanPriceRepository(session),
        entitlements=EntitlementRepository(session),
        audit_log=AuditLogRepository(session),
    )


PlanServiceDep = Annotated[PlanService, Depends(get_plan_service)]


async def get_current_admin(
    session: SessionDep,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> AdminUser:
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing admin access token.")
    token = authorization.removeprefix("Bearer ")
    try:
        admin_id = decode_admin_access_token(token, jwt_secret=settings.jwt_secret)
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token.") from exc

    admin = await AdminUserRepository(session).get(admin_id)
    if admin is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token.")
    return admin


CurrentAdminDep = Annotated[AdminUser, Depends(get_current_admin)]


def require_permission(permission: Permission) -> Any:
    """
    §29 RBAC — usage: `_: Annotated[None, Depends(require_permission(Permission.KYC_QUEUE_VIEW))]`.
    DB-driven per ADR 0011: checks `admin_role_permissions` directly
    rather than a hardcoded Python mapping — a `super_admin`-only RBAC
    management screen can now change what a role can do by writing rows,
    no deploy required.
    """

    async def _check(admin: CurrentAdminDep, session: SessionDep) -> None:
        if not await AdminRoleRepository(session).role_has_permission(
            admin.role_id, permission.value
        ):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions.")

    return Depends(_check)
