from fastapi import APIRouter, HTTPException, status

from app.api.v1.admin_deps import AdminAuthServiceDep, CurrentAdminDep
from app.domain.admin.auth_service import AdminAuthError
from app.schemas.admin import (
    AdminCompleteLoginRequest,
    AdminEnrollMfaRequest,
    AdminLoginRequest,
    AdminLoginStartResponse,
    AdminMeResponse,
    AdminSessionResponse,
)

router = APIRouter(prefix="/admin/auth", tags=["admin-auth"])


def _as_http_error(exc: AdminAuthError) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc))


@router.post("/login/start", response_model=AdminLoginStartResponse)
async def start_login(
    body: AdminLoginRequest, service: AdminAuthServiceDep
) -> AdminLoginStartResponse:
    try:
        result = await service.start_login(email=body.email, password=body.password)
    except AdminAuthError as exc:
        raise _as_http_error(exc) from exc
    return AdminLoginStartResponse(
        status=result.status,
        mfa_enroll_token=result.mfa_enroll_token,
        provisioning_uri=result.provisioning_uri,
        login_token=result.login_token,
    )


@router.post("/mfa/enroll", response_model=AdminSessionResponse)
async def enroll_mfa(
    body: AdminEnrollMfaRequest, service: AdminAuthServiceDep
) -> AdminSessionResponse:
    try:
        session = await service.enroll_mfa(enroll_token=body.enroll_token, code=body.code)
    except AdminAuthError as exc:
        raise _as_http_error(exc) from exc
    return AdminSessionResponse(
        access_token=session.access_token, email=session.admin.email, role=session.role_name
    )


@router.post("/login/complete", response_model=AdminSessionResponse)
async def complete_login(
    body: AdminCompleteLoginRequest, service: AdminAuthServiceDep
) -> AdminSessionResponse:
    try:
        session = await service.complete_login(login_token=body.login_token, code=body.code)
    except AdminAuthError as exc:
        raise _as_http_error(exc) from exc
    return AdminSessionResponse(
        access_token=session.access_token, email=session.admin.email, role=session.role_name
    )


@router.post("/logout", status_code=204)
async def logout(admin: CurrentAdminDep, service: AdminAuthServiceDep) -> None:
    await service.logout(admin.id)


@router.get("/me", response_model=AdminMeResponse)
async def get_me(admin: CurrentAdminDep, service: AdminAuthServiceDep) -> AdminMeResponse:
    role_name = await service.get_role_name(admin)
    return AdminMeResponse(email=admin.email, role=role_name)
