"""
Admin authentication — docs/DITSALA_MASTER_SPEC.md §29: "All admin
accounts require MFA enrollment before first use (TOTP at minimum)."
Framework-agnostic per §3.3.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import jwt

from app.core.security import (
    create_admin_access_token,
    create_admin_login_token,
    create_admin_mfa_enroll_token,
    decode_admin_login_token,
    decode_admin_mfa_enroll_token,
    generate_totp_secret,
    totp_provisioning_uri,
    verify_secret,
    verify_totp,
)
from app.models.admin import AdminUser, AuditLog
from app.repositories.admin import AdminRoleRepository, AdminUserRepository, AuditLogRepository


class AdminAuthError(Exception):
    """Raised for admin-auth preconditions a caller should turn into a 401/4xx, not a 500."""


@dataclass(frozen=True)
class AdminLoginStart:
    status: Literal["mfa_enroll_required", "mfa_code_required"]
    mfa_enroll_token: str | None = None
    provisioning_uri: str | None = None
    login_token: str | None = None


@dataclass(frozen=True)
class AdminSession:
    access_token: str
    admin: AdminUser
    role_name: str


class AdminAuthService:
    def __init__(
        self,
        *,
        admin_users: AdminUserRepository,
        admin_roles: AdminRoleRepository,
        audit_log: AuditLogRepository,
        jwt_secret: str,
        access_token_ttl_minutes: int,
    ) -> None:
        self._admin_users = admin_users
        self._admin_roles = admin_roles
        self._audit_log = audit_log
        self._jwt_secret = jwt_secret
        self._access_token_ttl_minutes = access_token_ttl_minutes

    async def start_login(self, *, email: str, password: str) -> AdminLoginStart:
        admin = await self._admin_users.get_by_email(email)
        if admin is None or not verify_secret(admin.password_hash, password):
            await self._log(None, "admin.login_failed", metadata_json={"email": email})
            raise AdminAuthError("Invalid email or password.")

        if not admin.mfa_enrolled:
            secret = generate_totp_secret()
            token = create_admin_mfa_enroll_token(
                admin.id, mfa_secret=secret, jwt_secret=self._jwt_secret
            )
            return AdminLoginStart(
                status="mfa_enroll_required",
                mfa_enroll_token=token,
                provisioning_uri=totp_provisioning_uri(secret=secret, email=admin.email),
            )

        login_token = create_admin_login_token(admin.id, jwt_secret=self._jwt_secret)
        return AdminLoginStart(status="mfa_code_required", login_token=login_token)

    async def enroll_mfa(self, *, enroll_token: str, code: str) -> AdminSession:
        """Confirms the admin can actually generate a valid code with the
        freshly issued secret before persisting it — completes login too,
        so enrollment doesn't require a second round trip."""
        try:
            payload = decode_admin_mfa_enroll_token(enroll_token, jwt_secret=self._jwt_secret)
        except jwt.InvalidTokenError as exc:
            raise AdminAuthError("Invalid or expired enrollment session.") from exc
        if not verify_totp(secret=payload.mfa_secret, code=code):
            raise AdminAuthError("Incorrect code.")

        admin = await self._admin_users.get(payload.admin_id)
        if admin is None:
            raise AdminAuthError("Invalid or expired enrollment session.")
        admin.mfa_secret = payload.mfa_secret
        admin.mfa_enrolled = True
        admin.last_login_at = datetime.now(UTC)
        await self._log(admin.id, "admin.mfa_enrolled")
        await self._log(admin.id, "admin.login")
        return await self._issue_session(admin)

    async def complete_login(self, *, login_token: str, code: str) -> AdminSession:
        try:
            admin_id = decode_admin_login_token(login_token, jwt_secret=self._jwt_secret)
        except jwt.InvalidTokenError as exc:
            raise AdminAuthError("Invalid or expired login session.") from exc

        admin = await self._admin_users.get(admin_id)
        if admin is None or admin.mfa_secret is None:
            raise AdminAuthError("Invalid or expired login session.")
        if not verify_totp(secret=admin.mfa_secret, code=code):
            await self._log(admin.id, "admin.login_failed", metadata_json={"stage": "mfa"})
            raise AdminAuthError("Incorrect code.")

        admin.last_login_at = datetime.now(UTC)
        await self._log(admin.id, "admin.login")
        return await self._issue_session(admin)

    async def logout(self, admin_id: uuid.UUID) -> None:
        await self._log(admin_id, "admin.logout")

    async def get_role_name(self, admin: AdminUser) -> str:
        role = await self._admin_roles.get(admin.role_id)
        if role is None:
            raise AdminAuthError("Admin role no longer exists.")
        return role.name

    async def _issue_session(self, admin: AdminUser) -> AdminSession:
        role_name = await self.get_role_name(admin)
        access_token = create_admin_access_token(
            admin.id, jwt_secret=self._jwt_secret, ttl_minutes=self._access_token_ttl_minutes
        )
        return AdminSession(access_token=access_token, admin=admin, role_name=role_name)

    async def _log(
        self,
        admin_id: uuid.UUID | None,
        action: str,
        *,
        target_type: str | None = None,
        target_id: uuid.UUID | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> None:
        await self._audit_log.add(
            AuditLog(
                created_at=datetime.now(UTC),
                actor_type="admin",
                actor_id=admin_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                metadata_json=metadata_json,
            )
        )
