import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.v1.admin_deps import CurrentAdminDep, KycReviewServiceDep, require_permission
from app.domain.admin.kyc_review_service import KycReviewError
from app.domain.admin.rbac import Permission
from app.schemas.admin import (
    KycActionRequest,
    KycDetailResponse,
    KycDocumentResponse,
    KycFaceVerificationResponse,
    UserSummaryResponse,
)

router = APIRouter(
    prefix="/admin/kyc",
    tags=["admin-kyc"],
    dependencies=[require_permission(Permission.KYC_QUEUE_VIEW)],
)


def _as_http_error(exc: KycReviewError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.get("/queue", response_model=list[UserSummaryResponse])
async def list_queue(service: KycReviewServiceDep) -> list[UserSummaryResponse]:
    users = await service.list_queue()
    return [UserSummaryResponse.model_validate(u) for u in users]


@router.get("/{user_id}", response_model=KycDetailResponse)
async def get_detail(
    user_id: uuid.UUID,
    admin: CurrentAdminDep,
    service: KycReviewServiceDep,
    reason: Annotated[str, Query(min_length=1)],
) -> KycDetailResponse:
    """§28.2/§5: a reason for access is required and logged *before* any
    P1 KYC detail is returned — `reason` is a required query param, not
    an afterthought header."""
    try:
        detail = await service.get_detail(admin_id=admin.id, user_id=user_id, reason=reason)
    except KycReviewError as exc:
        raise _as_http_error(exc) from exc
    return KycDetailResponse(
        user=UserSummaryResponse.model_validate(detail.user),
        documents=[KycDocumentResponse.model_validate(d) for d in detail.documents],
        face_verifications=[
            KycFaceVerificationResponse.model_validate(f) for f in detail.face_verifications
        ],
    )


@router.post(
    "/{user_id}/approve",
    response_model=UserSummaryResponse,
    dependencies=[require_permission(Permission.KYC_QUEUE_ACTION)],
)
async def approve(
    user_id: uuid.UUID, body: KycActionRequest, admin: CurrentAdminDep, service: KycReviewServiceDep
) -> UserSummaryResponse:
    try:
        user = await service.approve(admin_id=admin.id, user_id=user_id, reason=body.reason)
    except KycReviewError as exc:
        raise _as_http_error(exc) from exc
    return UserSummaryResponse.model_validate(user)


@router.post(
    "/{user_id}/reject",
    response_model=UserSummaryResponse,
    dependencies=[require_permission(Permission.KYC_QUEUE_ACTION)],
)
async def reject(
    user_id: uuid.UUID, body: KycActionRequest, admin: CurrentAdminDep, service: KycReviewServiceDep
) -> UserSummaryResponse:
    try:
        user = await service.reject(admin_id=admin.id, user_id=user_id, reason=body.reason)
    except KycReviewError as exc:
        raise _as_http_error(exc) from exc
    return UserSummaryResponse.model_validate(user)


@router.post(
    "/{user_id}/request-recapture",
    response_model=UserSummaryResponse,
    dependencies=[require_permission(Permission.KYC_QUEUE_ACTION)],
)
async def request_recapture(
    user_id: uuid.UUID, body: KycActionRequest, admin: CurrentAdminDep, service: KycReviewServiceDep
) -> UserSummaryResponse:
    try:
        user = await service.request_recapture(
            admin_id=admin.id, user_id=user_id, reason=body.reason
        )
    except KycReviewError as exc:
        raise _as_http_error(exc) from exc
    return UserSummaryResponse.model_validate(user)
