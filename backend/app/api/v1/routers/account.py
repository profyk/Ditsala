from fastapi import APIRouter, HTTPException, status

from app.api.v1.deps import (
    AccountLifecycleServiceDep,
    ComplianceServiceDep,
    CurrentUserDep,
    ProfileServiceDep,
)
from app.domain.account.profile_service import ProfileError
from app.domain.account.service import AccountLifecycleError
from app.domain.compliance.service import ComplianceError
from app.schemas.account import (
    AccountDeactivationResponse,
    AvatarResponse,
    ConfirmAvatarRequest,
    RequestAvatarUploadRequest,
    RequestAvatarUploadResponse,
)
from app.schemas.compliance import DataSubjectRequestResponse, FileDataSubjectRequestRequest

router = APIRouter(prefix="/account", tags=["account"])


def _as_http_error(exc: AccountLifecycleError | ComplianceError | ProfileError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


# --- profile picture ---


@router.post("/avatar/upload-url", response_model=RequestAvatarUploadResponse)
async def request_avatar_upload(
    body: RequestAvatarUploadRequest, user: CurrentUserDep, service: ProfileServiceDep
) -> RequestAvatarUploadResponse:
    try:
        key, upload_url = await service.request_avatar_upload(
            user, content_type=body.content_type
        )
    except ProfileError as exc:
        raise _as_http_error(exc) from exc
    return RequestAvatarUploadResponse(key=key, upload_url=upload_url)


@router.post("/avatar/confirm", response_model=AvatarResponse)
async def confirm_avatar(
    body: ConfirmAvatarRequest, user: CurrentUserDep, service: ProfileServiceDep
) -> AvatarResponse:
    try:
        avatar_url = await service.confirm_avatar(user, key=body.key)
    except ProfileError as exc:
        raise _as_http_error(exc) from exc
    return AvatarResponse(avatar_url=avatar_url)


@router.delete("/avatar", status_code=204)
async def remove_avatar(user: CurrentUserDep, service: ProfileServiceDep) -> None:
    await service.remove_avatar(user)


@router.post("/deactivate", response_model=AccountDeactivationResponse)
async def deactivate_account(
    user: CurrentUserDep, service: AccountLifecycleServiceDep
) -> AccountDeactivationResponse:
    try:
        updated = await service.request_deactivation(user)
    except AccountLifecycleError as exc:
        raise _as_http_error(exc) from exc
    return AccountDeactivationResponse.model_validate(updated)


@router.post("/deactivate/cancel", response_model=AccountDeactivationResponse)
async def cancel_deactivation(
    user: CurrentUserDep, service: AccountLifecycleServiceDep
) -> AccountDeactivationResponse:
    try:
        updated = await service.cancel_deactivation(user)
    except AccountLifecycleError as exc:
        raise _as_http_error(exc) from exc
    return AccountDeactivationResponse.model_validate(updated)


# --- §34.4: data subject rights (self-service filing) ---


@router.post("/data-requests", response_model=DataSubjectRequestResponse, status_code=201)
async def file_data_subject_request(
    body: FileDataSubjectRequestRequest, user: CurrentUserDep, service: ComplianceServiceDep
) -> DataSubjectRequestResponse:
    try:
        request = await service.file_request(
            user, request_type=body.request_type, details=body.details
        )
    except ComplianceError as exc:
        raise _as_http_error(exc) from exc
    return DataSubjectRequestResponse.model_validate(request)


@router.get("/data-requests", response_model=list[DataSubjectRequestResponse])
async def list_own_data_subject_requests(
    user: CurrentUserDep, service: ComplianceServiceDep
) -> list[DataSubjectRequestResponse]:
    requests = await service.list_for_user(user.id)
    return [DataSubjectRequestResponse.model_validate(r) for r in requests]
