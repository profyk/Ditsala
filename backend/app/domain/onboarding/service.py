"""
Onboarding orchestration — docs/DITSALA_MASTER_SPEC.md §9-15. Owns the
account_state transitions (§14) for everything up to `pending_code`;
completing onboarding into `active` requires device + Signal key
registration, which is Phase 3's job (auth/sessions) — deliberately not
implemented here, per "build in order, don't skip ahead."

Framework-agnostic: no FastAPI/HTTP concerns, only repositories and the
provider Protocols (§3.3).
"""

from datetime import UTC, datetime, timedelta

from app.core.security import (
    generate_numeric_code,
    hash_secret,
    is_breached_code,
    validate_ditsala_code_strength,
    verify_secret,
)
from app.domain.onboarding.interfaces import (
    EmailProvider,
    KycJobType,
    KycOutcome,
    KycProvider,
    KycSdkToken,
    KycWebhookResult,
    OtpProvider,
)
from app.domain.ratelimit.interfaces import RateLimiter
from app.models.accounts import (
    EmailVerification,
    KycDocument,
    KycFaceVerification,
    NextOfKin,
    PhoneVerification,
    User,
)
from app.models.circle import Invitation
from app.repositories.admin import SystemConfigRepository
from app.repositories.circle import InvitationRepository
from app.repositories.kyc import KycDocumentRepository, KycFaceVerificationRepository
from app.repositories.users import (
    EmailVerificationRepository,
    NextOfKinRepository,
    PhoneVerificationRepository,
    UserRepository,
)

EMAIL_CODE_TTL_MINUTES = 10
MAX_EMAIL_CODE_ATTEMPTS = 5
MAX_KYC_ATTEMPTS_BEFORE_MANUAL_REVIEW = 3

# §32: per-account limits on OTP/email-code sends — per-IP is deliberately
# not layered on top of these. Pre-auth, the target address/number *is*
# the account identifier we have; post-signup there is no meaningful
# "account" distinct from it. See docs/adr/0010-rate-limiting-key-choice.md.
EMAIL_CODE_SEND_LIMIT = 5
EMAIL_CODE_SEND_WINDOW_SECONDS = 3600
PHONE_OTP_SEND_LIMIT = 5
PHONE_OTP_SEND_WINDOW_SECONDS = 3600


class OnboardingError(Exception):
    """Raised for onboarding preconditions a caller should turn into a 4xx, not a 500."""


class OnboardingService:
    def __init__(
        self,
        *,
        users: UserRepository,
        email_verifications: EmailVerificationRepository,
        phone_verifications: PhoneVerificationRepository,
        next_of_kin: NextOfKinRepository,
        kyc_documents: KycDocumentRepository,
        kyc_face_verifications: KycFaceVerificationRepository,
        invitations: InvitationRepository,
        system_config: SystemConfigRepository,
        email_provider: EmailProvider,
        otp_provider: OtpProvider,
        kyc_provider: KycProvider,
        rate_limiter: RateLimiter,
    ) -> None:
        self._users = users
        self._email_verifications = email_verifications
        self._phone_verifications = phone_verifications
        self._next_of_kin = next_of_kin
        self._kyc_documents = kyc_documents
        self._kyc_face_verifications = kyc_face_verifications
        self._invitations = invitations
        self._system_config = system_config
        self._email_provider = email_provider
        self._otp_provider = otp_provider
        self._kyc_provider = kyc_provider
        self._rate_limiter = rate_limiter

    # --- §9 step 1-2: email + personal info ---

    async def start_signup(
        self,
        *,
        email: str,
        phone: str,
        display_name: str,
        date_of_birth: datetime,
        national_id_hash: str,
        invite_code: str | None = None,
    ) -> User:
        invitation = await self._check_invite_only_mode(invite_code)
        if await self._users.get_by_email(email) is not None:
            raise OnboardingError("An account with this email already exists.")
        if await self._users.get_by_phone(phone) is not None:
            raise OnboardingError("An account with this phone number already exists.")
        user = await self._users.add(
            User(
                email=email,
                phone=phone,
                display_name=display_name,
                date_of_birth=date_of_birth,
                national_id_hash=national_id_hash,
            )
        )
        if invitation is not None:
            invitation.status = "redeemed"
            invitation.redeemed_by_user_id = user.id
        await self.request_email_verification(user)
        return user

    async def _check_invite_only_mode(self, invite_code: str | None) -> Invitation | None:
        """
        §22/§28: `system_config.invite_only_mode` gates *who can start
        onboarding*, never whether KYC is required — that stays mandatory
        regardless. Returns the invitation to redeem once signup actually
        succeeds (not redeemed here, so a failed signup below doesn't burn
        a single-use code).
        """
        config = await self._system_config.get_by_key("invite_only_mode")
        if config is None or not config.value.get("enabled"):
            return None
        if invite_code is None:
            raise OnboardingError("An invitation code is required to sign up at this time.")
        invitation = await self._invitations.get_by_code(invite_code)
        if invitation is None or invitation.status != "sent":
            raise OnboardingError("Invalid or already-used invitation code.")
        if invitation.expires_at < datetime.now(UTC):
            invitation.status = "expired"
            raise OnboardingError("This invitation code has expired.")
        return invitation

    async def request_email_verification(self, user: User) -> None:
        await self._rate_limiter.hit(
            f"onboarding:email_code:{user.email}",
            limit=EMAIL_CODE_SEND_LIMIT,
            window_seconds=EMAIL_CODE_SEND_WINDOW_SECONDS,
        )
        code = generate_numeric_code()
        await self._email_verifications.add(
            EmailVerification(
                user_id=user.id,
                code_ref=hash_secret(code),
                expires_at=datetime.now(UTC) + timedelta(minutes=EMAIL_CODE_TTL_MINUTES),
            )
        )
        await self._email_provider.send_verification_code(to_email=user.email, code=code)

    async def confirm_email_verification(self, user: User, submitted_code: str) -> None:
        if user.account_state != "pending_email":
            raise OnboardingError(f"Cannot verify email in state {user.account_state!r}.")

        verification = await self._email_verifications.get_latest_pending(user.id)
        if verification is None:
            raise OnboardingError("No pending email verification — request a new code.")
        if verification.expires_at < datetime.now(UTC):
            verification.status = "expired"
            raise OnboardingError("This code has expired — request a new one.")
        verification.attempt_count += 1
        if verification.attempt_count > MAX_EMAIL_CODE_ATTEMPTS:
            verification.status = "expired"
            raise OnboardingError("Too many attempts — request a new code.")
        if not verify_secret(verification.code_ref, submitted_code):
            raise OnboardingError("Incorrect code.")

        verification.status = "verified"
        user.email_verified_at = datetime.now(UTC)
        user.account_state = "pending_phone"

    # --- §9 step 3, §11: phone via Twilio Verify ---

    async def request_phone_verification(self, user: User) -> None:
        if user.account_state != "pending_phone":
            raise OnboardingError(f"Cannot verify phone in state {user.account_state!r}.")
        await self._rate_limiter.hit(
            f"onboarding:phone_otp:{user.phone}",
            limit=PHONE_OTP_SEND_LIMIT,
            window_seconds=PHONE_OTP_SEND_WINDOW_SECONDS,
        )
        provider_sid = await self._otp_provider.start_verification(phone_number=user.phone)
        await self._phone_verifications.add(
            PhoneVerification(
                user_id=user.id,
                code_ref=provider_sid,
                expires_at=datetime.now(UTC) + timedelta(minutes=EMAIL_CODE_TTL_MINUTES),
            )
        )

    async def confirm_phone_verification(self, user: User, submitted_code: str) -> None:
        if user.account_state != "pending_phone":
            raise OnboardingError(f"Cannot verify phone in state {user.account_state!r}.")
        if not await self._otp_provider.check_verification(
            phone_number=user.phone, code=submitted_code
        ):
            raise OnboardingError("Incorrect code.")

        verification = await self._phone_verifications.get_latest_pending(user.id)
        if verification is not None:
            verification.status = "verified"
        user.phone_verified_at = datetime.now(UTC)
        user.account_state = "pending_kyc_document"

    # --- §9 step 4, §12: Smile ID document capture ---

    async def start_kyc_document_capture(
        self, user: User, *, document_type: str
    ) -> KycSdkToken:
        if user.account_state not in ("pending_kyc_document", "manual_review"):
            raise OnboardingError(f"Cannot start KYC document capture in state "
                                   f"{user.account_state!r}.")
        sdk_token = await self._kyc_provider.create_sdk_token(
            user_id=user.id, job_type=KycJobType.DOCUMENT_VERIFICATION
        )
        await self._kyc_documents.add(
            KycDocument(
                user_id=user.id,
                document_type=document_type,
                smile_id_job_id=sdk_token.job_id,
            )
        )
        return sdk_token

    async def handle_kyc_document_result(self, user: User, result: KycWebhookResult) -> None:
        document = await self._kyc_documents.get_by_smile_id_job(result.job_id)
        if document is None or document.user_id != user.id:
            raise OnboardingError("Unknown or mismatched KYC document job.")

        document.result_summary = result.result_summary
        if result.outcome == KycOutcome.PASSED:
            document.status = "passed"
            user.account_state = "pending_kyc_liveness"
        elif result.outcome == KycOutcome.MANUAL_REVIEW:
            document.status = "manual_review"
            user.account_state = "manual_review"
        else:
            document.status = "failed"
            fail_count = await self._kyc_documents.count_failed(user.id)
            if fail_count >= MAX_KYC_ATTEMPTS_BEFORE_MANUAL_REVIEW:
                user.account_state = "manual_review"

    # --- §9 step 5, §12: SmartSelfie liveness + face match ---

    async def start_kyc_liveness(self, user: User) -> KycSdkToken:
        if user.account_state not in ("pending_kyc_liveness", "manual_review"):
            raise OnboardingError(f"Cannot start KYC liveness in state {user.account_state!r}.")
        sdk_token = await self._kyc_provider.create_sdk_token(
            user_id=user.id, job_type=KycJobType.SMARTSELFIE
        )
        # Pre-created here, not lazily in handle_kyc_liveness_result: the
        # webhook router looks a job up by id to find *which user* it
        # belongs to before it can call that method at all, so the row
        # must already exist by the time the webhook arrives. (This
        # mirrors start_kyc_document_capture, which already did this
        # correctly — this one was a real bug, caught while building
        # Phase 3's analogous login-liveness flow.)
        await self._kyc_face_verifications.add(
            KycFaceVerification(user_id=user.id, smile_id_job_id=sdk_token.job_id)
        )
        return sdk_token

    async def handle_kyc_liveness_result(self, user: User, result: KycWebhookResult) -> None:
        face = await self._kyc_face_verifications.get_by_smile_id_job(result.job_id)
        if face is None:
            raise OnboardingError("Unknown KYC liveness job.")
        if face.user_id != user.id:
            raise OnboardingError("Mismatched KYC liveness job.")

        face.selfie_liveness_score = result.result_summary.get("confidence_value")
        face.face_match_score = result.result_summary.get("confidence_value")
        if result.outcome == KycOutcome.PASSED:
            face.status = "passed"
            face.verified_at = datetime.now(UTC)
            user.account_state = "pending_next_of_kin"
        elif result.outcome == KycOutcome.MANUAL_REVIEW:
            user.account_state = "manual_review"
        else:
            face.status = "failed"
            fail_count = await self._kyc_face_verifications.count_failed(user.id)
            if fail_count >= MAX_KYC_ATTEMPTS_BEFORE_MANUAL_REVIEW:
                user.account_state = "manual_review"

    # --- §9 step 6, §13: next of kin ---

    async def add_next_of_kin(
        self, user: User, *, full_name: str, relationship: str, phone: str, email: str | None
    ) -> NextOfKin:
        if user.account_state not in ("pending_next_of_kin", "active"):
            raise OnboardingError(f"Cannot add next of kin in state {user.account_state!r}.")
        record = await self._next_of_kin.add(
            NextOfKin(
                user_id=user.id, full_name=full_name, relationship=relationship,
                phone=phone, email=email,
            )
        )
        if user.account_state == "pending_next_of_kin":
            user.account_state = "pending_code"
        return record

    # --- §9 step 7, §15: DITSALA Code ---

    async def set_ditsala_code(self, user: User, code: str) -> None:
        if user.account_state != "pending_code":
            raise OnboardingError(f"Cannot set the DITSALA Code in state {user.account_state!r}.")
        if not validate_ditsala_code_strength(code):
            raise OnboardingError(
                f"The DITSALA Code must be at least {8} characters and include a number."
            )
        if await is_breached_code(code):
            raise OnboardingError(
                "This code has appeared in a known data breach — choose a different one."
            )
        user.ditsala_code_hash = hash_secret(code)
        user.code_set_at = datetime.now(UTC)
        # Stays in `pending_code` — device + Signal key registration (Phase 3)
        # is what actually completes onboarding into `active`.
