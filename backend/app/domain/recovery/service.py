"""
Account recovery — docs/DITSALA_MASTER_SPEC.md §33. High-assurance path
for a user who has lost their device: email + phone re-verification,
Smile ID SmartSelfie *Authentication* (a 1:1 match against the user's
existing enrollment — never a document re-capture, never DITSALA
re-supplying a stored image, since none is stored, §5/§34), a next-of-kin
attestation window, then a full session reset (§33 step 4, delegated to
`AuthService.complete_recovery_session` — see that method's docstring for
why session/device issuance isn't duplicated here). Framework-agnostic
per §3.3.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.core.security import (
    create_recovery_flag_token,
    decode_recovery_flag_token,
    generate_numeric_code,
    hash_secret,
    is_breached_code,
    is_weak_pin,
    validate_ditsala_code_strength,
    validate_pin_strength,
    verify_secret,
)
from app.domain.auth.service import AuthService
from app.domain.notifications.interfaces import SmsProvider
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
from app.models.accounts import EmailVerification, User
from app.models.admin import AuditLog
from app.models.devices import AccountRecoveryRequest, Device
from app.repositories.admin import AuditLogRepository
from app.repositories.devices import AccountRecoveryRequestRepository
from app.repositories.users import (
    EmailVerificationRepository,
    NextOfKinRepository,
    UserRepository,
)

CODE_TTL_MINUTES = 10
MAX_CODE_ATTEMPTS = 5
LIVENESS_VALIDITY_MINUTES = 15

# §32: per-account (per-email) limit — see
# docs/adr/0010-rate-limiting-key-choice.md for why this isn't per-IP too.
RECOVERY_START_LIMIT = 5
RECOVERY_START_WINDOW_SECONDS = 3600


class RecoveryError(Exception):
    """Raised for recovery preconditions a caller should turn into a 4xx, not a 500."""


class RecoveryService:
    def __init__(
        self,
        *,
        users: UserRepository,
        next_of_kin: NextOfKinRepository,
        email_verifications: EmailVerificationRepository,
        recovery_requests: AccountRecoveryRequestRepository,
        audit_log: AuditLogRepository,
        auth_service: AuthService,
        email_provider: EmailProvider,
        otp_provider: OtpProvider,
        kyc_provider: KycProvider,
        sms_provider: SmsProvider,
        jwt_secret: str,
        rate_limiter: RateLimiter,
    ) -> None:
        self._users = users
        self._next_of_kin = next_of_kin
        self._email_verifications = email_verifications
        self._recovery_requests = recovery_requests
        self._audit_log = audit_log
        self._auth_service = auth_service
        self._email_provider = email_provider
        self._otp_provider = otp_provider
        self._kyc_provider = kyc_provider
        self._sms_provider = sms_provider
        self._jwt_secret = jwt_secret
        self._rate_limiter = rate_limiter

    # --- §33 step 1: email + phone re-verification ---

    async def start_recovery(self, *, email: str, phone: str) -> AccountRecoveryRequest:
        await self._rate_limiter.hit(
            f"recovery:start:{email}",
            limit=RECOVERY_START_LIMIT,
            window_seconds=RECOVERY_START_WINDOW_SECONDS,
        )
        user = await self._users.get_by_email(email)
        if user is None or user.phone != phone:
            # Same generic message either way — this endpoint must not be
            # usable to enumerate which emails/phones have an account.
            raise RecoveryError("No matching account found.")
        if user.account_state != "active":
            raise RecoveryError("No matching account found.")
        assert user.email is not None  # guaranteed: get_by_email only matches a set email

        request = await self._recovery_requests.add(AccountRecoveryRequest(user_id=user.id))
        await self._send_email_code(user)
        await self._otp_provider.start_verification(phone_number=user.phone)
        await self._log(request, "recovery.started")
        return request

    async def _send_email_code(self, user: User) -> None:
        assert user.email is not None  # only called from the email+phone recovery path
        code = generate_numeric_code()
        await self._email_verifications.add(
            EmailVerification(
                user_id=user.id,
                code_ref=hash_secret(code),
                expires_at=datetime.now(UTC) + timedelta(minutes=CODE_TTL_MINUTES),
            )
        )
        await self._email_provider.send_verification_code(to_email=user.email, code=code)

    async def _get_request(self, recovery_request_id: uuid.UUID) -> AccountRecoveryRequest:
        request = await self._recovery_requests.get(recovery_request_id)
        if request is None:
            raise RecoveryError("No such recovery request.")
        return request

    async def confirm_email(self, *, recovery_request_id: uuid.UUID, code: str) -> None:
        request = await self._get_request(recovery_request_id)
        verification = await self._email_verifications.get_latest_pending(request.user_id)
        if verification is None:
            raise RecoveryError("No pending email verification — start over.")
        if verification.expires_at < datetime.now(UTC):
            verification.status = "expired"
            raise RecoveryError("This code has expired.")
        verification.attempt_count += 1
        if verification.attempt_count > MAX_CODE_ATTEMPTS:
            verification.status = "expired"
            raise RecoveryError("Too many attempts — start over.")
        if not verify_secret(verification.code_ref, code):
            raise RecoveryError("Incorrect code.")
        verification.status = "verified"
        request.email_verified = True

    async def confirm_phone(self, *, recovery_request_id: uuid.UUID, code: str) -> None:
        request = await self._get_request(recovery_request_id)
        user = await self._users.get(request.user_id)
        assert user is not None
        if not await self._otp_provider.check_verification(
            phone_number=user.phone, code=code
        ):
            raise RecoveryError("Incorrect code.")
        request.phone_verified = True

    # --- ADR 0014: normal-tier phone-only recovery (no email, no liveness) ---

    async def start_phone_recovery(self, *, phone: str) -> AccountRecoveryRequest:
        """A `normal`-tier account has no email and no liveness
        enrollment — the only real re-verification available is the
        phone number itself. `vip` accounts are explicitly rejected
        here; a lighter recovery flow would undercut exactly the
        verified-identity promise VIP is sold on, so they keep the
        original email+phone+liveness `start_recovery` unchanged."""
        await self._rate_limiter.hit(
            f"recovery:start_phone:{phone}",
            limit=RECOVERY_START_LIMIT,
            window_seconds=RECOVERY_START_WINDOW_SECONDS,
        )
        user = await self._users.get_by_phone(phone)
        if user is None or user.account_state != "active" or user.account_tier != "normal":
            # Same generic message regardless of which check failed —
            # this endpoint must not be usable to enumerate accounts or
            # tiers.
            raise RecoveryError("No matching account found.")

        request = await self._recovery_requests.add(AccountRecoveryRequest(user_id=user.id))
        await self._otp_provider.start_verification(phone_number=user.phone)
        await self._log(request, "recovery.phone_started")
        return request

    async def confirm_phone_recovery(
        self, *, recovery_request_id: uuid.UUID, code: str
    ) -> None:
        request = await self._get_request(recovery_request_id)
        user = await self._users.get(request.user_id)
        assert user is not None
        if not await self._otp_provider.check_verification(
            phone_number=user.phone, code=code
        ):
            raise RecoveryError("Incorrect code.")
        request.phone_verified = True
        request.status = "phone_verified"
        await self._notify_next_of_kin(request)

    # --- §33 step 2: SmartSelfie Authentication (1:1 match) ---

    async def start_liveness(self, recovery_request_id: uuid.UUID) -> KycSdkToken:
        request = await self._get_request(recovery_request_id)
        if not (request.email_verified and request.phone_verified):
            raise RecoveryError("Confirm both email and phone before starting liveness.")
        token = await self._kyc_provider.create_sdk_token(
            user_id=request.user_id, job_type=KycJobType.RECOVERY_AUTHENTICATION
        )
        request.smile_id_job_id = token.job_id
        return token

    async def handle_liveness_webhook(self, result: KycWebhookResult) -> None:
        request = await self._recovery_requests.get_by_smile_id_job(result.job_id)
        if request is None:
            raise RecoveryError("Unknown recovery liveness job.")

        if result.outcome == KycOutcome.PASSED:
            request.status = "liveness_passed"
            await self._log(request, "recovery.liveness_passed")
            await self._notify_next_of_kin(request)
        else:
            request.status = "liveness_failed"
            await self._log(request, "recovery.liveness_failed")

    # --- §33 step 3: next-of-kin attestation window ---

    async def _notify_next_of_kin(self, request: AccountRecoveryRequest) -> None:
        for kin in await self._next_of_kin.list_for_user(request.user_id):
            flag_token = create_recovery_flag_token(request.id, jwt_secret=self._jwt_secret)
            await self._sms_provider.send_sms(
                to_phone=kin.phone,
                body=(
                    "DITSALA: someone is recovering an account that lists you as next of "
                    f"kin. If this seems suspicious, tell us: https://ditsala.app/recovery/flag?token={flag_token}"
                ),
            )

    async def flag_by_token(self, token: str) -> AccountRecoveryRequest:
        try:
            request_id = decode_recovery_flag_token(token, jwt_secret=self._jwt_secret)
        except jwt.InvalidTokenError as exc:
            raise RecoveryError("Invalid or expired link.") from exc

        request = await self._get_request(request_id)
        if request.status not in ("aborted", "completed"):
            request.status = "next_of_kin_flagged"
            await self._log(request, "recovery.flagged_by_next_of_kin")
        return request

    # --- §33 step 4: completion ---

    async def complete(
        self,
        *,
        recovery_request_id: uuid.UUID,
        new_ditsala_code: str,
        device_name: str,
        platform: str,
        push_token: str | None,
    ) -> tuple[User, Device, str, str]:
        request = await self._get_request(recovery_request_id)
        user = await self._users.get(request.user_id)
        assert user is not None

        # ADR 0014: a `normal`-tier account completes via the phone-only
        # path (no liveness step exists for it) and sets a PIN, not the
        # original alphanumeric code.
        if user.account_tier == "normal":
            if request.status != "phone_verified":
                raise RecoveryError(
                    f"Cannot complete recovery in status {request.status!r} — "
                    "confirm your phone number first."
                )
            if not validate_pin_strength(new_ditsala_code):
                raise RecoveryError("Your PIN must be exactly 6 digits.")
            if is_weak_pin(new_ditsala_code):
                raise RecoveryError(
                    "That PIN is too easy to guess — avoid repeated or sequential digits."
                )
        else:
            if request.status not in ("liveness_passed", "next_of_kin_flagged"):
                raise RecoveryError(
                    f"Cannot complete recovery in status {request.status!r} — "
                    "SmartSelfie Authentication must pass first."
                )
            if not validate_ditsala_code_strength(new_ditsala_code):
                raise RecoveryError("DITSALA Code does not meet strength requirements.")
            if await is_breached_code(new_ditsala_code):
                raise RecoveryError(
                    "This code has appeared in a known data breach — choose a different one."
                )

        user.ditsala_code_hash = hash_secret(new_ditsala_code)
        user.code_set_at = datetime.now(UTC)
        user.failed_code_attempts = 0
        user.locked_until = None

        device, access_token, refresh_token = await self._auth_service.complete_recovery_session(
            user, device_name=device_name, platform=platform, push_token=push_token
        )
        request.status = "completed"
        request.new_device_id = device.id
        request.completed_at = datetime.now(UTC)
        await self._log(request, "recovery.completed")
        return user, device, access_token, refresh_token

    async def _log(self, request: AccountRecoveryRequest, action: str) -> None:
        await self._audit_log.add(
            AuditLog(
                created_at=datetime.now(UTC),
                actor_type="user",
                actor_id=request.user_id,
                action=action,
                target_type="account_recovery_request",
                target_id=request.id,
            )
        )
