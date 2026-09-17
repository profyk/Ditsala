from datetime import datetime, time
from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Request, status

from app.api.v1.deps import CurrentUserDep, SettingsDep, VipUpgradeServiceDep
from app.core.security import hash_national_id
from app.domain.billing.service import VipUpgradeError
from app.schemas.billing import (
    VipKycDocumentStartRequest,
    VipKycSdkTokenResponse,
    VipUpgradeInitiationResponse,
    VipUpgradeStartRequest,
)
from app.services.factory import get_payment_provider

router = APIRouter(prefix="/account/vip", tags=["billing"])
webhook_router = APIRouter(tags=["webhooks"])


def _as_http_error(exc: VipUpgradeError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.post("/upgrade/start", response_model=VipUpgradeInitiationResponse)
async def start_vip_upgrade(
    user: CurrentUserDep,
    service: VipUpgradeServiceDep,
    settings: SettingsDep,
    body: Annotated[VipUpgradeStartRequest, Body(default_factory=VipUpgradeStartRequest)],
) -> VipUpgradeInitiationResponse:
    try:
        initiation = await service.start_upgrade(
            user,
            email=body.email,
            date_of_birth=(
                datetime.combine(body.date_of_birth, time.min) if body.date_of_birth else None
            ),
            national_id_hash=(
                hash_national_id(body.national_id, pepper=settings.national_id_pepper)
                if body.national_id
                else None
            ),
        )
    except VipUpgradeError as exc:
        raise _as_http_error(exc) from exc
    return VipUpgradeInitiationResponse(
        payment_url=initiation.payment_url, external_reference=initiation.external_reference
    )


@router.post("/kyc/document/start", response_model=VipKycSdkTokenResponse)
async def start_vip_kyc_document(
    body: VipKycDocumentStartRequest, user: CurrentUserDep, service: VipUpgradeServiceDep
) -> VipKycSdkTokenResponse:
    try:
        token = await service.start_kyc_document(user, document_type=body.document_type)
    except VipUpgradeError as exc:
        raise _as_http_error(exc) from exc
    return VipKycSdkTokenResponse(token=token.token, job_id=token.job_id)


@router.post("/kyc/liveness/start", response_model=VipKycSdkTokenResponse)
async def start_vip_kyc_liveness(
    user: CurrentUserDep, service: VipUpgradeServiceDep
) -> VipKycSdkTokenResponse:
    try:
        token = await service.start_kyc_liveness(user)
    except VipUpgradeError as exc:
        raise _as_http_error(exc) from exc
    return VipKycSdkTokenResponse(token=token.token, job_id=token.job_id)


@webhook_router.post("/webhooks/stitch", include_in_schema=False)
async def stitch_webhook(
    request: Request, service: VipUpgradeServiceDep, settings: SettingsDep
) -> dict[str, str]:
    payload = await request.body()
    signature = request.headers.get("X-Stitch-Signature", "")
    result = get_payment_provider(settings).verify_and_parse_webhook(
        payload=payload, signature=signature
    )
    if result is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid webhook signature.")
    try:
        await service.handle_payment_webhook(result)
    except VipUpgradeError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"status": "ok"}
