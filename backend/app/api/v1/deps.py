import hashlib
import uuid
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_db_session
from app.core.security import decode_access_token, decode_meet_host_token, decode_onboarding_token
from app.domain.account.profile_service import ProfileService
from app.domain.account.service import AccountLifecycleService
from app.domain.auth.service import AuthService
from app.domain.billing.conference_upgrade import ConferencePlanUpgradeService
from app.domain.billing.plans import PlanService
from app.domain.billing.service import VipUpgradeService
from app.domain.calls.service import CallService
from app.domain.circle.service import CircleService
from app.domain.compliance.export import DataExportService
from app.domain.compliance.service import ComplianceService
from app.domain.location.service import LocationService
from app.domain.meet_ai.service import MeetingIntelligenceService
from app.domain.meetings.service import MeetingService
from app.domain.messaging.service import MessagingService
from app.domain.onboarding.service import OnboardingService
from app.domain.recovery.service import RecoveryService
from app.domain.sos.service import SosService
from app.domain.translation.service import TranslationService
from app.domain.vip_chat.service import VipChatService
from app.models.accounts import User
from app.models.devices import Device
from app.repositories.admin import AuditLogRepository, SystemConfigRepository
from app.repositories.billing import (
    ConferencePlanPurchaseRepository,
    EntitlementRepository,
    PlanPriceRepository,
    PlanRepository,
    VipSubscriptionRepository,
)
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
from app.repositories.meetings import (
    BreakoutRoomParticipantRepository,
    BreakoutRoomRepository,
    MeetingAiNoteRepository,
    MeetingDocumentRepository,
    MeetingMessageRepository,
    MeetingParticipantRepository,
    MeetingPollRepository,
    MeetingPollVoteRepository,
    MeetingQuestionRepository,
    MeetingRecordingRepository,
    MeetingRegistrationRepository,
    MeetingRepository,
    MeetingTranscriptRepository,
)
from app.repositories.messages import (
    MediaObjectRepository,
    MessageReceiptRepository,
    MessageRepository,
)
from app.repositories.sos import SosEventRepository, SosNotificationRepository
from app.repositories.translation import (
    ConferenceLanguagePreferenceRepository,
    InterpreterSessionRepository,
    TranslationRequestRepository,
    TranslationUsageRepository,
    UserLanguagePreferenceRepository,
    VipMessageRepository,
    VipMessageTranslationRepository,
)
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
    get_translation_provider,
)
from app.services.meet.livekit import LiveKitRoomProvider
from app.services.meet_ai.claude import ClaudeMeetingIntelligenceProvider
from app.services.meet_ai.deepgram import DeepgramTranscriptionProvider
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


async def get_meeting_actor(
    meeting_id: uuid.UUID,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> uuid.UUID:
    """Resolves to a user id for meeting-management actions (recording,
    document upload/delete) from either a normal access token or a
    short-lived meet-host token (`POST /meetings/{id}/host-link`). The
    fallback exists because `apps/meet` is a separate origin with no session
    of its own — a host opening their meeting from the mobile app's "My
    Meetings" list authenticates there via the scoped token, not a real
    access token, so these host-only actions need to accept both. A
    meet-host token minted for one meeting is rejected outright for any
    other meeting_id, even though it decodes fine — the FastAPI path param
    is trusted, the token's own embedded meeting_id is not."""
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing credentials.")
    token = authorization.removeprefix("Bearer ")
    try:
        return decode_access_token(token, jwt_secret=settings.jwt_secret).user_id
    except jwt.InvalidTokenError:
        pass
    try:
        token_meeting_id, user_id = decode_meet_host_token(token, jwt_secret=settings.jwt_secret)
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid or expired credentials."
        ) from exc
    if token_meeting_id != meeting_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This link isn't valid for this meeting.")
    return user_id


MeetingActorDep = Annotated[uuid.UUID, Depends(get_meeting_actor)]


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
        users=UserRepository(session),
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


async def get_profile_service(session: SessionDep, settings: SettingsDep) -> ProfileService:
    return ProfileService(
        users=UserRepository(session), storage_provider=get_storage_provider(settings)
    )


ProfileServiceDep = Annotated[ProfileService, Depends(get_profile_service)]


async def get_compliance_service(
    session: SessionDep, account_lifecycle: AccountLifecycleServiceDep, settings: SettingsDep
) -> ComplianceService:
    return ComplianceService(
        requests=DataSubjectRequestRepository(session),
        users=UserRepository(session),
        account_lifecycle=account_lifecycle,
        export=DataExportService(session=session, storage=get_storage_provider(settings)),
    )


ComplianceServiceDep = Annotated[ComplianceService, Depends(get_compliance_service)]


async def get_plan_service(session: SessionDep) -> PlanService:
    """Defined here (not `admin_deps.py`) since it's now a dependency of
    `get_meeting_service` below, which admin_deps.py itself imports
    `SessionDep`/`SettingsDep` from — putting it there instead would be a
    circular import. `admin_deps.py`'s admin-only `/admin/billing/plans/*`
    routes import `PlanServiceDep` from here too, so there's exactly one
    place this service gets constructed."""
    return PlanService(
        plans=PlanRepository(session),
        plan_prices=PlanPriceRepository(session),
        entitlements=EntitlementRepository(session),
        audit_log=AuditLogRepository(session),
        users=UserRepository(session),
    )


PlanServiceDep = Annotated[PlanService, Depends(get_plan_service)]


async def get_meeting_service(
    session: SessionDep, settings: SettingsDep, plans: PlanServiceDep
) -> MeetingService:
    return MeetingService(
        meetings=MeetingRepository(session),
        participants=MeetingParticipantRepository(session),
        recordings=MeetingRecordingRepository(session),
        messages=MeetingMessageRepository(session),
        polls=MeetingPollRepository(session),
        poll_votes=MeetingPollVoteRepository(session),
        questions=MeetingQuestionRepository(session),
        breakout_rooms=BreakoutRoomRepository(session),
        breakout_room_participants=BreakoutRoomParticipantRepository(session),
        registrations=MeetingRegistrationRepository(session),
        documents=MeetingDocumentRepository(session),
        room_provider=LiveKitRoomProvider.from_settings(settings),
        storage_provider=get_storage_provider(settings),
        conference_language_preferences=ConferenceLanguagePreferenceRepository(session),
        # Called directly (not as a `TranslationServiceDep` param) since this
        # function is defined above that dependency in this file — same
        # session/settings, so it resolves to an identical TranslationService.
        translation_service=await get_translation_service(session, settings),
        users=UserRepository(session),
        plans=plans,
    )


MeetingServiceDep = Annotated[MeetingService, Depends(get_meeting_service)]


async def get_meeting_intelligence_service(
    session: SessionDep, settings: SettingsDep
) -> MeetingIntelligenceService:
    return MeetingIntelligenceService(
        meetings=MeetingRepository(session),
        participants=MeetingParticipantRepository(session),
        recordings=MeetingRecordingRepository(session),
        transcripts=MeetingTranscriptRepository(session),
        notes=MeetingAiNoteRepository(session),
        storage_provider=get_storage_provider(settings),
        transcription_provider=DeepgramTranscriptionProvider.from_settings(settings),
        intelligence_provider=ClaudeMeetingIntelligenceProvider.from_settings(settings),
    )


MeetingIntelligenceServiceDep = Annotated[
    MeetingIntelligenceService, Depends(get_meeting_intelligence_service)
]


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


async def get_conference_plan_upgrade_service(
    session: SessionDep, settings: SettingsDep, plans: PlanServiceDep
) -> ConferencePlanUpgradeService:
    return ConferencePlanUpgradeService(
        purchases=ConferencePlanPurchaseRepository(session),
        plans=plans,
        payment_provider=get_payment_provider(settings),
    )


ConferencePlanUpgradeServiceDep = Annotated[
    ConferencePlanUpgradeService, Depends(get_conference_plan_upgrade_service)
]


async def get_translation_service(session: SessionDep, settings: SettingsDep) -> TranslationService:
    return TranslationService(
        translation_requests=TranslationRequestRepository(session),
        translation_usage=TranslationUsageRepository(session),
        user_language_preferences=UserLanguagePreferenceRepository(session),
        interpreter_sessions=InterpreterSessionRepository(session),
        system_config=SystemConfigRepository(session),
        provider=get_translation_provider(settings),
    )


TranslationServiceDep = Annotated[TranslationService, Depends(get_translation_service)]


async def get_vip_chat_service(
    session: SessionDep, translation: TranslationServiceDep
) -> VipChatService:
    return VipChatService(
        conversations=ConversationRepository(session),
        conversation_members=ConversationMemberRepository(session),
        vip_messages=VipMessageRepository(session),
        vip_message_translations=VipMessageTranslationRepository(session),
        users=UserRepository(session),
        contacts=ContactRepository(session),
        blocks=BlockRepository(session),
        language_preferences=UserLanguagePreferenceRepository(session),
        devices=DeviceRepository(session),
        translation_service=translation,
        connection_manager=connection_manager,
    )


VipChatServiceDep = Annotated[VipChatService, Depends(get_vip_chat_service)]
