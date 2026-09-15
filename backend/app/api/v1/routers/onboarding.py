from datetime import datetime, time

from fastapi import APIRouter, HTTPException, Request, status

from app.api.v1.deps import OnboardingServiceDep, OnboardingUserDep, SessionDep, SettingsDep
from app.core.security import create_onboarding_token, hash_national_id
from app.domain.onboarding.interfaces import KycJobType
from app.domain.onboarding.service import OnboardingError
from app.repositories.kyc import KycDocumentRepository, KycFaceVerificationRepository
from app.repositories.users import UserRepository
from app.schemas.onboarding import (
    AccountStateResponse,
    CodeConfirmRequest,
    DitsalaCodeRequest,
    KycDocumentStartRequest,
    KycSdkTokenResponse,
    NextOfKinRequest,
    OnboardingSessionResponse,
    SignupRequest,
)
from app.services.factory import get_kyc_provider

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


def _as_http_error(exc: OnboardingError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.post("/signup", response_model=OnboardingSessionResponse, status_code=201)
async def signup(
    body: SignupRequest, service: OnboardingServiceDep, settings: SettingsDep
) -> OnboardingSessionResponse:
    try:
        user = await service.start_signup(
            email=body.email,
            phone=body.phone,
            display_name=body.display_name,
            date_of_birth=datetime.combine(body.date_of_birth, time.min),
            national_id_hash=hash_national_id(
                body.national_id, pepper=settings.national_id_pepper
            ),
        )
    except OnboardingError as exc:
        raise _as_http_error(exc) from exc
    token = create_onboarding_token(user.id, jwt_secret=settings.jwt_secret)
    return OnboardingSessionResponse(onboarding_token=token, account_state=user.account_state)


@router.post("/email/resend", response_model=AccountStateResponse)
async def resend_email_code(
    user: OnboardingUserDep, service: OnboardingServiceDep
) -> AccountStateResponse:
    await service.request_email_verification(user)
    return AccountStateResponse(account_state=user.account_state)


@router.post("/email/confirm", response_model=AccountStateResponse)
async def confirm_email(
    body: CodeConfirmRequest, user: OnboardingUserDep, service: OnboardingServiceDep
) -> AccountStateResponse:
    try:
        await service.confirm_email_verification(user, body.code)
    except OnboardingError as exc:
        raise _as_http_error(exc) from exc
    return AccountStateResponse(account_state=user.account_state)


@router.post("/phone/request", response_model=AccountStateResponse)
async def request_phone_code(
    user: OnboardingUserDep, service: OnboardingServiceDep
) -> AccountStateResponse:
    try:
        await service.request_phone_verification(user)
    except OnboardingError as exc:
        raise _as_http_error(exc) from exc
    return AccountStateResponse(account_state=user.account_state)


@router.post("/phone/confirm", response_model=AccountStateResponse)
async def confirm_phone(
    body: CodeConfirmRequest, user: OnboardingUserDep, service: OnboardingServiceDep
) -> AccountStateResponse:
    try:
        await service.confirm_phone_verification(user, body.code)
    except OnboardingError as exc:
        raise _as_http_error(exc) from exc
    return AccountStateResponse(account_state=user.account_state)


@router.post("/kyc/document/start", response_model=KycSdkTokenResponse)
async def start_kyc_document(
    body: KycDocumentStartRequest, user: OnboardingUserDep, service: OnboardingServiceDep
) -> KycSdkTokenResponse:
    try:
        sdk_token = await service.start_kyc_document_capture(
            user, document_type=body.document_type
        )
    except OnboardingError as exc:
        raise _as_http_error(exc) from exc
    return KycSdkTokenResponse(token=sdk_token.token, job_id=sdk_token.job_id)


@router.post("/kyc/liveness/start", response_model=KycSdkTokenResponse)
async def start_kyc_liveness(
    user: OnboardingUserDep, service: OnboardingServiceDep
) -> KycSdkTokenResponse:
    try:
        sdk_token = await service.start_kyc_liveness(user)
    except OnboardingError as exc:
        raise _as_http_error(exc) from exc
    return KycSdkTokenResponse(token=sdk_token.token, job_id=sdk_token.job_id)


@router.post("/next-of-kin", response_model=AccountStateResponse)
async def add_next_of_kin(
    body: NextOfKinRequest, user: OnboardingUserDep, service: OnboardingServiceDep
) -> AccountStateResponse:
    try:
        await service.add_next_of_kin(
            user,
            full_name=body.full_name,
            relationship=body.relationship,
            phone=body.phone,
            email=body.email,
        )
    except OnboardingError as exc:
        raise _as_http_error(exc) from exc
    return AccountStateResponse(account_state=user.account_state)


@router.post("/code", response_model=AccountStateResponse)
async def set_ditsala_code(
    body: DitsalaCodeRequest, user: OnboardingUserDep, service: OnboardingServiceDep
) -> AccountStateResponse:
    try:
        await service.set_ditsala_code(user, body.code)
    except OnboardingError as exc:
        raise _as_http_error(exc) from exc
    return AccountStateResponse(account_state=user.account_state)


webhook_router = APIRouter(tags=["webhooks"])


@webhook_router.post("/webhooks/smile-id", include_in_schema=False)
async def smile_id_webhook(
    request: Request, session: SessionDep, service: OnboardingServiceDep, settings: SettingsDep
) -> dict[str, str]:
    payload = await request.body()
    signature = request.headers.get("X-Smile-Signature", "")
    result = get_kyc_provider(settings).verify_and_parse_webhook(
        payload=payload, signature=signature
    )
    if result is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid webhook signature.")

    if result.job_type == KycJobType.DOCUMENT_VERIFICATION:
        document = await KycDocumentRepository(session).get_by_smile_id_job(result.job_id)
        if document is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown job.")
        user = await UserRepository(session).get(document.user_id)
        assert user is not None
        await service.handle_kyc_document_result(user, result)
    else:
        face = await KycFaceVerificationRepository(session).get_by_smile_id_job(result.job_id)
        if face is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown job.")
        user = await UserRepository(session).get(face.user_id)
        assert user is not None
        await service.handle_kyc_liveness_result(user, result)

    return {"status": "ok"}
