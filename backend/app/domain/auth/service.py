"""
Two-factor login, device registry, and session issuance —
docs/DITSALA_MASTER_SPEC.md §14, §16-17. Owns the account_state -> active
transition (device + Signal key registration completes onboarding); Signal
key upload itself is Phase 4's concern (see repositories/crypto.py).

Full server-side authentication (new device, after logout, recovery) always
requires DITSALA Code + a fresh SmartSelfie liveness check — never code
alone, per §17. Routine unlock on an already-trusted device is a client-side
concern (local biometric gating a stored refresh token) that only ever
calls `refresh_session` here — it never re-authenticates from scratch.
"""

import uuid
from datetime import UTC, datetime, timedelta

from app.core.security import (
    LoginTokenPayload,
    create_access_token,
    create_login_token,
    generate_refresh_token,
    hash_refresh_token,
    verify_secret,
)
from app.domain.onboarding.interfaces import (
    KycJobType,
    KycOutcome,
    KycProvider,
    KycSdkToken,
    KycWebhookResult,
)
from app.models.accounts import KycFaceVerification, User
from app.models.devices import Device, LoginAttempt, Session
from app.repositories.devices import (
    DeviceRepository,
    LoginAttemptRepository,
    SessionRepository,
)
from app.repositories.kyc import KycFaceVerificationRepository
from app.repositories.users import UserRepository

MAX_CODE_ATTEMPTS = 5
LOCKOUT_BASE_MINUTES = 5
LOCKOUT_CAP_MINUTES = 24 * 60
LIVENESS_VALIDITY_MINUTES = 15


class AuthError(Exception):
    """Raised for auth preconditions a caller should turn into a 4xx, not a 500."""


class AuthService:
    def __init__(
        self,
        *,
        users: UserRepository,
        devices: DeviceRepository,
        sessions: SessionRepository,
        login_attempts: LoginAttemptRepository,
        kyc_face_verifications: KycFaceVerificationRepository,
        kyc_provider: KycProvider,
        jwt_secret: str,
        access_token_ttl_minutes: int,
    ) -> None:
        self._users = users
        self._devices = devices
        self._sessions = sessions
        self._login_attempts = login_attempts
        self._kyc_face_verifications = kyc_face_verifications
        self._kyc_provider = kyc_provider
        self._jwt_secret = jwt_secret
        self._access_token_ttl_minutes = access_token_ttl_minutes

    # --- §9 step 8: completing onboarding ---

    async def complete_onboarding_device(
        self, user: User, *, device_name: str, platform: str, push_token: str | None
    ) -> tuple[Device, str, str]:
        if user.account_state != "pending_code" or user.ditsala_code_hash is None:
            raise AuthError(f"Cannot complete onboarding in state {user.account_state!r}.")

        now = datetime.now(UTC)
        device = await self._devices.add(
            Device(
                user_id=user.id,
                device_name=device_name,
                platform=platform,
                push_token=push_token,
                first_seen_at=now,
                last_seen_at=now,
                # Trusted immediately — this is the same session that just
                # completed KYC liveness, not a fresh, unverified device.
                is_trusted=True,
            )
        )
        user.account_state = "active"
        access_token, refresh_token = await self._issue_session(user, device)
        return device, access_token, refresh_token

    # --- §17: two-factor login (code, then a fresh liveness check) ---

    async def start_login(
        self,
        *,
        identifier: str,
        ditsala_code: str,
        device_name: str,
        platform: str,
        push_token: str | None,
        ip_hash: str,
    ) -> tuple[str, KycSdkToken]:
        user = await self._users.get_by_email(identifier) or await self._users.get_by_phone(
            identifier
        )
        if user is None:
            await self._login_attempts.add(
                LoginAttempt(
                    user_id=None, ip_hash=ip_hash, stage="code", outcome="failure"
                )
            )
            raise AuthError("Invalid credentials.")

        if user.locked_until is not None and user.locked_until > datetime.now(UTC):
            raise AuthError("This account is temporarily locked. Try again later.")

        if user.ditsala_code_hash is None or not verify_secret(
            user.ditsala_code_hash, ditsala_code
        ):
            await self._register_code_failure(user, ip_hash=ip_hash)
            raise AuthError("Invalid credentials.")

        user.failed_code_attempts = 0
        user.locked_until = None
        await self._login_attempts.add(
            LoginAttempt(user_id=user.id, ip_hash=ip_hash, stage="code", outcome="success")
        )

        sdk_token = await self._kyc_provider.create_sdk_token(
            user_id=user.id, job_type=KycJobType.LOGIN_LIVENESS
        )
        # Pre-created so the webhook can identify the user by job id alone
        # (see the Phase 2 bug this pattern fixed, ADR-worthy on its own).
        await self._kyc_face_verifications.add(
            KycFaceVerification(user_id=user.id, smile_id_job_id=sdk_token.job_id)
        )
        login_token = create_login_token(
            LoginTokenPayload(
                user_id=user.id,
                job_id=sdk_token.job_id,
                device_name=device_name,
                platform=platform,
                push_token=push_token,
            ),
            jwt_secret=self._jwt_secret,
        )
        return login_token, sdk_token

    async def _register_code_failure(self, user: User, *, ip_hash: str) -> None:
        user.failed_code_attempts += 1
        if user.failed_code_attempts >= MAX_CODE_ATTEMPTS:
            excess = user.failed_code_attempts - MAX_CODE_ATTEMPTS
            minutes = min(LOCKOUT_BASE_MINUTES * (2**excess), LOCKOUT_CAP_MINUTES)
            user.locked_until = datetime.now(UTC) + timedelta(minutes=minutes)
        await self._login_attempts.add(
            LoginAttempt(user_id=user.id, ip_hash=ip_hash, stage="code", outcome="failure")
        )

    async def record_login_liveness_result(self, result: KycWebhookResult) -> None:
        """Called from the webhook — only records the liveness result.
        Whether it's good enough to actually complete a login is decided
        synchronously in `complete_login`, when the client asks."""
        face = await self._kyc_face_verifications.get_by_smile_id_job(result.job_id)
        if face is None:
            raise AuthError("Unknown login-liveness job.")
        face.selfie_liveness_score = result.result_summary.get("confidence_value")
        face.face_match_score = result.result_summary.get("confidence_value")
        face.status = "passed" if result.outcome == KycOutcome.PASSED else "failed"
        if face.status == "passed":
            face.verified_at = datetime.now(UTC)

    async def complete_login(self, payload: LoginTokenPayload, *, ip_hash: str) -> tuple[
        User, Device, str, str
    ]:
        user = await self._users.get(payload.user_id)
        if user is None:
            raise AuthError("Invalid login session.")

        face = await self._kyc_face_verifications.get_by_smile_id_job(payload.job_id)
        if (
            face is None
            or face.status != "passed"
            or face.verified_at is None
            or face.verified_at < datetime.now(UTC) - timedelta(minutes=LIVENESS_VALIDITY_MINUTES)
        ):
            await self._login_attempts.add(
                LoginAttempt(
                    user_id=user.id, ip_hash=ip_hash, stage="face_liveness", outcome="failure"
                )
            )
            raise AuthError("Liveness check has not passed yet.")

        await self._login_attempts.add(
            LoginAttempt(
                user_id=user.id, ip_hash=ip_hash, stage="face_liveness", outcome="success"
            )
        )

        now = datetime.now(UTC)
        existing_devices = await self._devices.list_for_user(user.id)
        device = next(
            (d for d in existing_devices if d.device_name == payload.device_name), None
        )
        if device is None:
            device = await self._devices.add(
                Device(
                    user_id=user.id,
                    device_name=payload.device_name,
                    platform=payload.platform,
                    push_token=payload.push_token,
                    first_seen_at=now,
                    last_seen_at=now,
                    is_trusted=True,  # earned by passing code + fresh liveness, right now
                )
            )
        else:
            device.last_seen_at = now
            device.is_trusted = True
            device.push_token = payload.push_token

        access_token, refresh_token = await self._issue_session(user, device)
        return user, device, access_token, refresh_token

    # --- §16: refresh rotation with reuse detection ---

    async def refresh_session(self, refresh_token: str) -> tuple[str, str]:
        token_hash = hash_refresh_token(refresh_token)
        session = await self._sessions.get_by_refresh_token_hash(token_hash)
        if session is None:
            raise AuthError("Invalid refresh token.")

        if session.revoked_at is not None:
            # A previously-rotated-away token being replayed is a strong
            # compromise signal — revoke every session in the family, not
            # just this one, per docs/DITSALA_MASTER_SPEC.md §16.
            family = await self._sessions.list_by_family(session.access_token_family_id)
            for member in family:
                if member.revoked_at is None:
                    member.revoked_at = datetime.now(UTC)
                    member.revoked_reason = "refresh token reuse detected"
            raise AuthError("This session has been revoked.")

        if session.expires_at < datetime.now(UTC):
            raise AuthError("This session has expired.")

        user = await self._users.get(session.user_id)
        if user is None:
            raise AuthError("Invalid refresh token.")

        session.revoked_at = datetime.now(UTC)
        session.revoked_reason = "rotated"

        new_refresh_token = generate_refresh_token()
        await self._sessions.add(
            Session(
                user_id=session.user_id,
                device_id=session.device_id,
                refresh_token_hash=hash_refresh_token(new_refresh_token),
                access_token_family_id=session.access_token_family_id,
                expires_at=datetime.now(UTC) + timedelta(days=30),
            )
        )
        access_token = create_access_token(
            session.user_id,
            session.device_id,
            jwt_secret=self._jwt_secret,
            ttl_minutes=self._access_token_ttl_minutes,
        )
        return access_token, new_refresh_token

    async def logout(self, refresh_token: str) -> None:
        session = await self._sessions.get_by_refresh_token_hash(hash_refresh_token(refresh_token))
        if session is not None and session.revoked_at is None:
            session.revoked_at = datetime.now(UTC)
            session.revoked_reason = "logout"

    # --- §16: device registry, revocation ---

    async def list_devices(self, user: User) -> list[Device]:
        return await self._devices.list_for_user(user.id)

    async def revoke_device(self, user: User, device_id: uuid.UUID) -> None:
        device = await self._devices.get(device_id)
        if device is None or device.user_id != user.id:
            raise AuthError("Unknown device.")
        device.revoked_at = datetime.now(UTC)
        for session in await self._sessions.list_active_for_user(user.id):
            if session.device_id == device_id:
                session.revoked_at = datetime.now(UTC)
                session.revoked_reason = "device revoked"

    async def revoke_all_sessions(self, user: User) -> None:
        for session in await self._sessions.list_active_for_user(user.id):
            session.revoked_at = datetime.now(UTC)
            session.revoked_reason = "logout everywhere"

    # --- helpers ---

    async def _issue_session(self, user: User, device: Device) -> tuple[str, str]:
        refresh_token = generate_refresh_token()
        family_id = uuid.uuid4()
        await self._sessions.add(
            Session(
                user_id=user.id,
                device_id=device.id,
                refresh_token_hash=hash_refresh_token(refresh_token),
                access_token_family_id=family_id,
                expires_at=datetime.now(UTC) + timedelta(days=30),
            )
        )
        access_token = create_access_token(
            user.id,
            device.id,
            jwt_secret=self._jwt_secret,
            ttl_minutes=self._access_token_ttl_minutes,
        )
        return access_token, refresh_token
