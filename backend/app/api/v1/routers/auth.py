import uuid

import jwt
from fastapi import APIRouter, HTTPException, status

from app.api.v1.deps import (
    AuthServiceDep,
    ClientIpHashDep,
    CurrentUserDep,
    OnboardingUserDep,
    SettingsDep,
)
from app.core.security import decode_login_token
from app.domain.auth.service import AuthError
from app.schemas.auth import (
    DeviceRegistrationRequest,
    DeviceResponse,
    LoginCompleteRequest,
    LoginStartRequest,
    LoginStartResponse,
    RefreshRequest,
    RefreshResponse,
    SessionResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _as_http_error(exc: AuthError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.post("/complete-onboarding", response_model=SessionResponse)
async def complete_onboarding(
    body: DeviceRegistrationRequest, user: OnboardingUserDep, service: AuthServiceDep
) -> SessionResponse:
    """§9 step 8 — device registration completes onboarding into `active`."""
    try:
        device, access_token, refresh_token = await service.complete_onboarding_device(
            user, device_name=body.device_name, platform=body.platform, push_token=body.push_token
        )
    except AuthError as exc:
        raise _as_http_error(exc) from exc
    return SessionResponse(
        access_token=access_token, refresh_token=refresh_token, device_id=device.id
    )


@router.post("/login/start", response_model=LoginStartResponse)
async def login_start(
    body: LoginStartRequest, service: AuthServiceDep, ip_hash: ClientIpHashDep
) -> LoginStartResponse:
    try:
        login_token, sdk_token = await service.start_login(
            identifier=body.identifier,
            ditsala_code=body.ditsala_code,
            device_name=body.device_name,
            platform=body.platform,
            push_token=body.push_token,
            ip_hash=ip_hash,
        )
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    return LoginStartResponse(
        login_token=login_token, kyc_token=sdk_token.token, job_id=sdk_token.job_id
    )


@router.post("/login/complete", response_model=SessionResponse)
async def login_complete(
    body: LoginCompleteRequest,
    service: AuthServiceDep,
    settings: SettingsDep,
    ip_hash: ClientIpHashDep,
) -> SessionResponse:
    try:
        payload = decode_login_token(body.login_token, jwt_secret=settings.jwt_secret)
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid or expired login session."
        ) from exc

    try:
        _user, device, access_token, refresh_token = await service.complete_login(
            payload, ip_hash=ip_hash
        )
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    return SessionResponse(
        access_token=access_token, refresh_token=refresh_token, device_id=device.id
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(body: RefreshRequest, service: AuthServiceDep) -> RefreshResponse:
    try:
        access_token, refresh_token = await service.refresh_session(body.refresh_token)
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    return RefreshResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/logout", status_code=204)
async def logout(body: RefreshRequest, service: AuthServiceDep) -> None:
    await service.logout(body.refresh_token)


@router.post("/logout-all", status_code=204)
async def logout_all(user: CurrentUserDep, service: AuthServiceDep) -> None:
    await service.revoke_all_sessions(user)


@router.get("/devices", response_model=list[DeviceResponse])
async def list_devices(user: CurrentUserDep, service: AuthServiceDep) -> list[DeviceResponse]:
    devices = await service.list_devices(user)
    return [DeviceResponse.model_validate(d) for d in devices]


@router.delete("/devices/{device_id}", status_code=204)
async def revoke_device(
    device_id: uuid.UUID, user: CurrentUserDep, service: AuthServiceDep
) -> None:
    try:
        await service.revoke_device(user, device_id)
    except AuthError as exc:
        raise _as_http_error(exc) from exc
