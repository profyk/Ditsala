import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# docs/DITSALA_MASTER_SPEC.md §14
ACCOUNT_STATES = (
    "pending_email",
    "pending_phone",
    "pending_kyc_document",
    "pending_kyc_liveness",
    "pending_next_of_kin",
    "pending_code",
    "active",
    "manual_review",
    "suspended",
    "deactivated",
    "banned",
)


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    display_name: Mapped[str] = mapped_column(String(120))
    date_of_birth: Mapped[datetime] = mapped_column(DateTime(timezone=False))
    # P1 — see app.domain.classification. Hash only, never plaintext.
    national_id_hash: Mapped[str] = mapped_column(String(128), unique=True)
    account_state: Mapped[str] = mapped_column(
        Enum(*ACCOUNT_STATES, name="account_state", native_enum=False, validate_strings=True),
        default="pending_email",
        server_default=text("'pending_email'"),
    )
    # P0 — see app.domain.classification. Argon2id, never plaintext.
    ditsala_code_hash: Mapped[str | None] = mapped_column(String(256))
    code_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_code_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # §34.2 deletion cascade: set whenever account_state transitions to
    # `deactivated` (self-service, 30-day reversible grace) or `banned`
    # (immediate, no grace unless trust_safety places a hold — §34.2's
    # "effectively the same 30-day operational window unless flagged").
    # A scheduled sweep hard-deletes once `hard_delete_after` elapses;
    # deleting the row cascades to everything else via the FK graph
    # (every `users.id` FK in this schema is `ondelete="CASCADE"`).
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hard_delete_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KycDocument(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "kyc_documents"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    document_type: Mapped[str] = mapped_column(
        Enum("sa_id", "passport", name="kyc_document_type", native_enum=False)
    )
    # The only pointer to imagery — DITSALA never copies raw images into its
    # own storage. See docs/DITSALA_MASTER_SPEC.md §5, §34.2.
    smile_id_job_id: Mapped[str] = mapped_column(String(128), unique=True)
    capture_method: Mapped[str] = mapped_column(
        Enum("camera_live", name="kyc_capture_method", native_enum=False),
        default="camera_live",
        server_default=text("'camera_live'"),
    )
    status: Mapped[str] = mapped_column(
        Enum(
            "pending", "passed", "failed", "manual_review",
            name="kyc_document_status", native_enum=False,
        ),
        default="pending",
        server_default=text("'pending'"),
    )
    # Non-reversible fields only (scores/decision) — no imagery. P1.
    result_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class KycFaceVerification(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "kyc_face_verifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    smile_id_job_id: Mapped[str] = mapped_column(String(128), unique=True)
    selfie_liveness_score: Mapped[float | None] = mapped_column()
    face_match_score: Mapped[float | None] = mapped_column()
    status: Mapped[str] = mapped_column(
        Enum(
            "pending", "passed", "failed",
            name="kyc_face_verification_status", native_enum=False,
        ),
        default="pending",
        server_default=text("'pending'"),
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NextOfKin(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "next_of_kin"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    full_name: Mapped[str] = mapped_column(String(200))
    relationship: Mapped[str] = mapped_column(String(60))
    phone: Mapped[str] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(320))
    notified_on_sos: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )


class EmailVerification(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "email_verifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    code_ref: Mapped[str] = mapped_column(String(128))
    channel: Mapped[str] = mapped_column(
        String(32), default="email", server_default=text("'email'")
    )
    status: Mapped[str] = mapped_column(
        Enum("pending", "verified", "expired", name="verification_status", native_enum=False),
        default="pending",
        server_default=text("'pending'"),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))


class PhoneVerification(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "phone_verifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    code_ref: Mapped[str] = mapped_column(String(128))
    channel: Mapped[str] = mapped_column(
        String(32), default="sms", server_default=text("'sms'")
    )
    status: Mapped[str] = mapped_column(
        Enum("pending", "verified", "expired", name="verification_status", native_enum=False),
        default="pending",
        server_default=text("'pending'"),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))


DATA_SUBJECT_REQUEST_TYPES = ("access", "correction", "deletion")
DATA_SUBJECT_REQUEST_STATUSES = ("pending", "in_progress", "completed", "rejected")


class DataSubjectRequest(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """docs/DITSALA_MASTER_SPEC.md §34.4 — access/correction/deletion
    requests, user-filed and admin-actioned, tracked against a 30-day
    response SLA (`due_at`, computed at filing time)."""

    __tablename__ = "data_subject_requests"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    request_type: Mapped[str] = mapped_column(
        Enum(
            *DATA_SUBJECT_REQUEST_TYPES,
            name="data_subject_request_type",
            native_enum=False,
            validate_strings=True,
        )
    )
    status: Mapped[str] = mapped_column(
        Enum(
            *DATA_SUBJECT_REQUEST_STATUSES,
            name="data_subject_request_status",
            native_enum=False,
            validate_strings=True,
        ),
        default="pending",
        server_default=text("'pending'"),
    )
    details: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    actioned_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="SET NULL")
    )
