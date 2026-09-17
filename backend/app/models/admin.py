import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# docs/DITSALA_MASTER_SPEC.md §29 — launch role set. Extensible via the
# admin_roles/admin_permissions tables; this tuple just seeds them.
ADMIN_ROLES = ("super_admin", "kyc_reviewer", "trust_safety", "support_readonly")


class AdminRole(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "admin_roles"

    name: Mapped[str] = mapped_column(String(64), unique=True)


class AdminPermission(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "admin_permissions"

    name: Mapped[str] = mapped_column(String(64), unique=True)


class AdminRolePermission(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "admin_role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission_id"),)

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_roles.id", ondelete="CASCADE"), index=True
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_permissions.id", ondelete="CASCADE"), index=True
    )


class AdminUser(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "admin_users"

    email: Mapped[str] = mapped_column(String(320), unique=True)
    # P0 — Argon2id, same standard as users.ditsala_code_hash.
    password_hash: Mapped[str] = mapped_column(String(256))
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_roles.id", ondelete="RESTRICT"), index=True
    )
    mfa_enrolled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    # Base32 TOTP secret, plaintext at rest — see docs/SECURITY_GAPS.md:
    # a production deployment should envelope-encrypt this with a KMS,
    # not done here since no KMS is provisioned in this environment.
    mfa_secret: Mapped[str | None] = mapped_column(String(64))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # A deactivated admin can't start a new login — but an already-issued
    # access token (up to admin_access_token_ttl_minutes old) stays valid
    # until it naturally expires, since there's no server-side admin
    # session/revocation list yet (see docs/SECURITY_GAPS.md).
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))


class AuditLog(Base, UUIDPrimaryKeyMixin):
    """
    Append-only — see docs/DITSALA_MASTER_SPEC.md §30. UPDATE/DELETE are
    revoked for every application-facing role in the classification
    migration (0002_classification_roles_rls); this model has no
    TimestampMixin.updated_at deliberately, since a row is never updated.
    """

    __tablename__ = "audit_log"

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    actor_type: Mapped[str] = mapped_column(String(16))  # admin | system | user
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    action: Mapped[str] = mapped_column(String(128))
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # Never message plaintext — see §5.
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class SystemConfig(Base):
    """Admin-tunable flags (§28.8) — e.g. invite_only_mode, sos_cancel_window_seconds."""

    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="SET NULL")
    )
