import hashlib
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_db_session
from app.core.security import decode_access_token, decode_onboarding_token
from app.domain.auth.service import AuthService
from app.domain.messaging.service import MessagingService
from app.domain.onboarding.service import OnboardingService
from app.models.accounts import User
from app.models.devices import Device
from app.repositories.circle import BlockRepository
from app.repositories.conversations import ConversationMemberRepository, ConversationRepository
from app.repositories.crypto import (
    IdentityKeyRepository,
    OneTimePrekeyRepository,
    SenderKeyRepository,
    SignedPrekeyRepository,
)
from app.repositories.devices import (
    DeviceRepository,
    LoginAttemptRepository,
    SessionRepository,
)
from app.repositories.kyc import KycDocumentRepository, KycFaceVerificationRepository
from app.repositories.messages import (
    MediaObjectRepository,
    MessageReceiptRepository,
    MessageRepository,
)
from app.repositories.users import (
    EmailVerificationRepository,
    NextOfKinRepository,
    PhoneVerificationRepository,
    UserRepository,
)
from app.services.factory import (
    get_email_provider,
    get_kyc_provider,
    get_otp_provider,
    get_storage_provider,
)
from app.services.realtime.websocket_manager import connection_manager

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


async def get_auth_service(session: SessionDep, settings: SettingsDep) -> AuthService:
    return AuthService(
        users=UserRepository(session),
        devices=DeviceRepository(session),
        sessions=SessionRepository(session),
        login_attempts=LoginAttemptRepository(session),
        kyc_face_verifications=KycFaceVerificationRepository(session),
        kyc_provider=get_kyc_provider(settings),
        jwt_secret=settings.jwt_secret,
        access_token_ttl_minutes=settings.access_token_ttl_minutes,
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def get_client_ip_hash(request: Request) -> str:
    """P3 metadata (§5) — client IP for login-attempt anomaly detection
    (§30), not tied to a specific user identity beyond that log row."""
    client_ip = request.client.host if request.client else "unknown"
    return hashlib.sha256(client_ip.encode()).hexdigest()


ClientIpHashDep = Annotated[str, Depends(get_client_ip_hash)]


async def get_current_user(
    session: SessionDep,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Real session auth (§16-17) — distinct from OnboardingUserDep, whose
    token can only ever reach `pending_code`, never touch this dependency's
    routes."""
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing access token.")
    token = authorization.removeprefix("Bearer ")
    try:
        payload = decode_access_token(token, jwt_secret=settings.jwt_secret)
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token.") from exc

    user = await UserRepository(session).get(payload.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token.")
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


async def get_current_device(
    session: SessionDep,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> Device:
    """Messaging operations (send, key registration) are per-device, not
    just per-user (§6) — the access token's device_id claim is what makes
    that possible without a second round trip."""
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing access token.")
    token = authorization.removeprefix("Bearer ")
    try:
        payload = decode_access_token(token, jwt_secret=settings.jwt_secret)
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token.") from exc

    device = await DeviceRepository(session).get(payload.device_id)
    if device is None or device.user_id != payload.user_id or device.revoked_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token.")
    return device


CurrentDeviceDep = Annotated[Device, Depends(get_current_device)]


async def get_current_device_from_ws_token(
    session: SessionDep, settings: SettingsDep, token: str
) -> Device:
    """Same checks as get_current_device, but for the WebSocket handshake,
    where the token arrives as a query parameter (`?token=...`) — browsers
    and React Native's WebSocket implementation don't support setting a
    custom Authorization header on the upgrade request."""
    try:
        payload = decode_access_token(token, jwt_secret=settings.jwt_secret)
    except jwt.InvalidTokenError as exc:
        raise ValueError("Invalid or expired token.") from exc
    device = await DeviceRepository(session).get(payload.device_id)
    if device is None or device.user_id != payload.user_id or device.revoked_at is not None:
        raise ValueError("Invalid or expired token.")
    return device


async def get_messaging_service(session: SessionDep, settings: SettingsDep) -> MessagingService:
    return MessagingService(
        identity_keys=IdentityKeyRepository(session),
        signed_prekeys=SignedPrekeyRepository(session),
        one_time_prekeys=OneTimePrekeyRepository(session),
        sender_keys=SenderKeyRepository(session),
        conversations=ConversationRepository(session),
        conversation_members=ConversationMemberRepository(session),
        messages=MessageRepository(session),
        message_receipts=MessageReceiptRepository(session),
        media_objects=MediaObjectRepository(session),
        devices=DeviceRepository(session),
        blocks=BlockRepository(session),
        storage_provider=get_storage_provider(settings),
        connection_manager=connection_manager,
    )


MessagingServiceDep = Annotated[MessagingService, Depends(get_messaging_service)]
