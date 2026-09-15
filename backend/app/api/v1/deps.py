from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_db_session
from app.core.security import decode_onboarding_token
from app.domain.onboarding.service import OnboardingService
from app.models.accounts import User
from app.repositories.kyc import KycDocumentRepository, KycFaceVerificationRepository
from app.repositories.users import (
    EmailVerificationRepository,
    NextOfKinRepository,
    PhoneVerificationRepository,
    UserRepository,
)
from app.services.factory import get_email_provider, get_kyc_provider, get_otp_provider

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


async def get_onboarding_service(
    session: SessionDep, settings: SettingsDep
) -> OnboardingService:
    return OnboardingService(
        users=UserRepository(session),
        email_verifications=EmailVerificationRepository(session),
        phone_verifications=PhoneVerificationRepository(session),
        next_of_kin=NextOfKinRepository(session),
        kyc_documents=KycDocumentRepository(session),
        kyc_face_verifications=KycFaceVerificationRepository(session),
        email_provider=get_email_provider(settings),
        otp_provider=get_otp_provider(settings),
        kyc_provider=get_kyc_provider(settings),
    )


OnboardingServiceDep = Annotated[OnboardingService, Depends(get_onboarding_service)]


async def get_current_onboarding_user(
    session: SessionDep,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing onboarding token.")
    token = authorization.removeprefix("Bearer ")
    try:
        user_id = decode_onboarding_token(token, jwt_secret=settings.jwt_secret)
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token.") from exc

    user = await UserRepository(session).get(user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token.")
    return user


OnboardingUserDep = Annotated[User, Depends(get_current_onboarding_user)]
