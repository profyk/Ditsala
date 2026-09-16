import hashlib
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_db_session
from app.core.security import decode_access_token, decode_onboarding_token
from app.domain.account.service import AccountLifecycleService
from app.domain.auth.service import AuthService
from app.domain.billing.service import VipUpgradeService
from app.domain.calls.service import CallService
from app.domain.circle.service import CircleService
from app.domain.compliance.service import ComplianceService
from app.domain.location.service import LocationService
from app.domain.meetings.service import MeetingService
from app.domain.messaging.service import MessagingService
from app.domain.onboarding.service import OnboardingService
from app.domain.recovery.service import RecoveryService
from app.domain.sos.service import SosService
from app.models.accounts import User
from app.models.devices import Device
from app.repositories.admin import AuditLogRepository, SystemConfigRepository
from app.repositories.billing import VipSubscriptionRepository
from app.repositories.calls import CallParticipantRepository, CallRepository
from app.repositories.circle import (
    BlockRepository,
    ContactRepository,
    ContactRequestRepository,
    InvitationRepository,
    ReportRepository,
)
from app.repositories.conversations import ConversationMemberRepository, ConversationRepository
from app.repositories.crypto import (
    IdentityKeyRepository,
    OneTimePrekeyRepository,
    SenderKeyRepository,
    SignedPrekeyRepository,
)
from app.repositories.devices import (
    AccountRecoveryRequestRepository,
    DeviceRepository,
    LoginAttemptRepository,
    SessionRepository,
)
from app.repositories.kyc import KycDocumentRepository, KycFaceVerificationRepository
from app.repositories.location import (
    LocationAccessLogRepository,
    LocationPingRepository,
    LocationShareRepository,
)
from app.repositories.meetings import MeetingParticipantRepository, MeetingRepository
from app.repositories.messages import (
    MediaObjectRepository,
    MessageReceiptRepository,
    MessageRepository,
)
from app.repositories.sos import SosEventRepository, SosNotificationRepository
from app.repositories.users import (
    DataSubjectRequestRepository,
    EmailVerificationRepository,
    NextOfKinRepository,
    PhoneVerificationRepository,
    UserRepository,
)
from app.services.factory import (
    get_email_provider,
    get_kyc_provider,
    get_otp_provider,
    get_payment_provider,
    get_push_provider,
    get_sms_provider,
    get_storage_provider,
)
from app.services.meet.livekit import LiveKitRoomProvider
from app.services.ratelimit.memory import rate_limiter
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
        invitations=InvitationRepository(session),
        system_config=SystemConfigRepository(session),
        email_provider=get_email_provider(settings),
        otp_provider=get_otp_provider(settings),
        kyc_provider=get_kyc_provider(settings),
        rate_limiter=rate_limiter,
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
        rate_limiter=rate_limiter,
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def get_recovery_service(session: SessionDep, settings: SettingsDep) -> RecoveryService:
    return RecoveryService(
        users=UserRepository(session),
        next_of_kin=NextOfKinRepository(session),
        email_verifications=EmailVerificationRepository(session),
        recovery_requests=AccountRecoveryRequestRepository(session),
        audit_log=AuditLogRepository(session),
        auth_service=await get_auth_service(session, settings),
        email_provider=get_email_provider(settings),
        otp_provider=get_otp_provider(settings),
        kyc_provider=get_kyc_provider(settings),
        sms_provider=get_sms_provider(settings),
        jwt_secret=settings.jwt_secret,
        rate_limiter=rate_limiter,
    )


RecoveryServiceDep = Annotated[RecoveryService, Depends(get_recovery_service)]


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
        contacts=ContactRepository(session),
        storage_provider=get_storage_provider(settings),
        connection_manager=connection_manager,
    )


MessagingServiceDep = Annotated[MessagingService, Depends(get_messaging_service)]


async def get_circle_service(session: SessionDep) -> CircleService:
    return CircleService(
        contacts=ContactRepository(session),
        contact_requests=ContactRequestRepository(session),
        invitations=InvitationRepository(session),
        blocks=BlockRepository(session),
        reports=ReportRepository(session),
        users=UserRepository(session),
        system_config=SystemConfigRepository(session),
        rate_limiter=rate_limiter,
    )


CircleServiceDep = Annotated[CircleService, Depends(get_circle_service)]


async def get_location_service(session: SessionDep) -> LocationService:
    return LocationService(
        shares=LocationShareRepository(session),
        pings=LocationPingRepository(session),
        access_log=LocationAccessLogRepository(session),
        contacts=ContactRepository(session),
    )


LocationServiceDep = Annotated[LocationService, Depends(get_location_service)]


async def get_sos_service(session: SessionDep, settings: SettingsDep) -> SosService:
    return SosService(
        sos_events=SosEventRepository(session),
        sos_notifications=SosNotificationRepository(session),
        contacts=ContactRepository(session),
        next_of_kin=NextOfKinRepository(session),
        devices=DeviceRepository(session),
        users=UserRepository(session),
        system_config=SystemConfigRepository(session),
        push_provider=get_push_provider(settings),
        sms_provider=get_sms_provider(settings),
        rate_limiter=rate_limiter,
    )


SosServiceDep = Annotated[SosService, Depends(get_sos_service)]


async def get_call_service(session: SessionDep) -> CallService:
    return CallService(
        calls=CallRepository(session),
        participants=CallParticipantRepository(session),
        conversations=ConversationRepository(session),
        conversation_members=ConversationMemberRepository(session),
        devices=DeviceRepository(session),
        connection_manager=connection_manager,
    )


CallServiceDep = Annotated[CallService, Depends(get_call_service)]


async def get_account_lifecycle_service(session: SessionDep) -> AccountLifecycleService:
    return AccountLifecycleService(
        users=UserRepository(session),
        audit_log=AuditLogRepository(session),
    )


AccountLifecycleServiceDep = Annotated[
    AccountLifecycleService, Depends(get_account_lifecycle_service)
]


async def get_compliance_service(
    session: SessionDep, account_lifecycle: AccountLifecycleServiceDep
) -> ComplianceService:
    return ComplianceService(
        requests=DataSubjectRequestRepository(session),
        users=UserRepository(session),
        account_lifecycle=account_lifecycle,
    )


ComplianceServiceDep = Annotated[ComplianceService, Depends(get_compliance_service)]


async def get_meeting_service(session: SessionDep, settings: SettingsDep) -> MeetingService:
    return MeetingService(
        meetings=MeetingRepository(session),
        participants=MeetingParticipantRepository(session),
        room_provider=LiveKitRoomProvider(
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
            livekit_url=settings.livekit_url,
        ),
    )


MeetingServiceDep = Annotated[MeetingService, Depends(get_meeting_service)]


async def get_vip_upgrade_service(session: SessionDep, settings: SettingsDep) -> VipUpgradeService:
    return VipUpgradeService(
        users=UserRepository(session),
        vip_subscriptions=VipSubscriptionRepository(session),
        kyc_documents=KycDocumentRepository(session),
        kyc_face_verifications=KycFaceVerificationRepository(session),
        system_config=SystemConfigRepository(session),
        payment_provider=get_payment_provider(settings),
        kyc_provider=get_kyc_provider(settings),
    )


VipUpgradeServiceDep = Annotated[VipUpgradeService, Depends(get_vip_upgrade_service)]
