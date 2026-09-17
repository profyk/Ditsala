import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Device(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "devices"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    device_name: Mapped[str] = mapped_column(String(120))
    platform: Mapped[str] = mapped_column(
        Enum("ios", "android", name="device_platform", native_enum=False)
    )
    push_token: Mapped[str | None] = mapped_column(String(256))
    signal_registration_id: Mapped[int | None] = mapped_column()
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_trusted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Session(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    # P0 — see app.domain.classification.
    refresh_token_hash: Mapped[str] = mapped_column(String(256))
    access_token_family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(String(200))


class LoginAttempt(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "login_attempts"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="SET NULL")
    )
    ip_hash: Mapped[str] = mapped_column(String(128))
    stage: Mapped[str] = mapped_column(
        Enum("code", "face_liveness", name="login_attempt_stage", native_enum=False)
    )
    outcome: Mapped[str] = mapped_column(
        Enum("success", "failure", name="login_attempt_outcome", native_enum=False)
    )


class AccountRecoveryRequest(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """docs/DITSALA_MASTER_SPEC.md §33."""

    __tablename__ = "account_recovery_requests"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(
        Enum(
            "initiated", "liveness_passed", "liveness_failed",
            "next_of_kin_flagged", "completed", "aborted",
            # ADR 0014 — the normal-tier phone-only recovery path's one
            # verification step; there's no liveness re-check to pass
            # (no enrollment exists), so this is that path's own
            # terminal "ready to complete" state.
            "phone_verified",
            name="account_recovery_status", native_enum=False,
        ),
        default="initiated",
        server_default=text("'initiated'"),
    )
    smile_id_job_id: Mapped[str | None] = mapped_column(String(128))
    new_device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="SET NULL")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # §33 step 1 — real gates `complete()` checks before allowing the
    # SmartSelfie Authentication step to even start, not just UI-level
    # sequencing.
    email_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    phone_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
