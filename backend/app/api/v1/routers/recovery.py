from fastapi import APIRouter, HTTPException, status

from app.api.v1.deps import RecoveryServiceDep
from app.domain.recovery.service import RecoveryError
from app.schemas.recovery import (
    CompleteRecoveryRequest,
    CompleteRecoveryResponse,
    ConfirmCodeRequest,
    FlagRecoveryResponse,
    KycSdkTokenResponse,
    LivenessStartRequest,
    RecoveryRequestResponse,
    StartRecoveryRequest,
)

router = APIRouter(prefix="/recovery", tags=["recovery"])


def _as_http_error(exc: RecoveryError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.post("/start", response_model=RecoveryRequestResponse)
async def start_recovery(
    body: StartRecoveryRequest, service: RecoveryServiceDep
) -> RecoveryRequestResponse:
    try:
        request = await service.start_recovery(email=body.email, phone=body.phone)
    except RecoveryError as exc:
        raise _as_http_error(exc) from exc
    return RecoveryRequestResponse.model_validate(request)


@router.post("/email/confirm", status_code=204)
async def confirm_email(body: ConfirmCodeRequest, service: RecoveryServiceDep) -> None:
    try:
        await service.confirm_email(recovery_request_id=body.recovery_request_id, code=body.code)
    except RecoveryError as exc:
        raise _as_http_error(exc) from exc


@router.post("/phone/confirm", status_code=204)
async def confirm_phone(body: ConfirmCodeRequest, service: RecoveryServiceDep) -> None:
    try:
        await service.confirm_phone(recovery_request_id=body.recovery_request_id, code=body.code)
    except RecoveryError as exc:
        raise _as_http_error(exc) from exc


@router.post("/liveness/start", response_model=KycSdkTokenResponse)
async def start_liveness(
    body: LivenessStartRequest, service: RecoveryServiceDep
) -> KycSdkTokenResponse:
    try:
        token = await service.start_liveness(body.recovery_request_id)
    except RecoveryError as exc:
        raise _as_http_error(exc) from exc
    return KycSdkTokenResponse(token=token.token, job_id=token.job_id)


@router.post("/complete", response_model=CompleteRecoveryResponse)
async def complete_recovery(
    body: CompleteRecoveryRequest, service: RecoveryServiceDep
) -> CompleteRecoveryResponse:
    try:
        _user, device, access_token, refresh_token = await service.complete(
            recovery_request_id=body.recovery_request_id,
            new_ditsala_code=body.new_ditsala_code,
            device_name=body.device_name,
            platform=body.platform,
            push_token=body.push_token,
        )
    except RecoveryError as exc:
        raise _as_http_error(exc) from exc
    return CompleteRecoveryResponse(
        access_token=access_token, refresh_token=refresh_token, device_id=device.id
    )


@router.get("/flag", response_model=FlagRecoveryResponse, include_in_schema=False)
async def flag_recovery(token: str, service: RecoveryServiceDep) -> FlagRecoveryResponse:
    """
    §33 step 3: the public, unauthenticated link texted to next-of-kin.
    Deliberately a plain GET so it opens directly from an SMS without any
    app/login — the token itself is the only credential (see
    `create_recovery_flag_token`'s docstring).
    """
    try:
        request = await service.flag_by_token(token)
    except RecoveryError as exc:
        raise _as_http_error(exc) from exc
    return FlagRecoveryResponse(status=request.status)
