import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# "Circle" in the UI; TRUSTED stays the backing enum value per brand rules.
CONTACT_TIERS = ("unverified", "verified", "trusted", "blocked")


class Contact(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("owner_user_id", "contact_user_id"),)

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    contact_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    tier: Mapped[str] = mapped_column(
        Enum(*CONTACT_TIERS, name="contact_tier", native_enum=False),
        default="unverified",
        server_default=text("'unverified'"),
    )
    safety_number_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ContactRequest(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "contact_requests"

    from_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    to_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(
        Enum("pending", "accepted", "declined", name="contact_request_status", native_enum=False),
        default="pending",
        server_default=text("'pending'"),
    )
    channel: Mapped[str] = mapped_column(
        Enum("qr", "invite_link", "phone_match", name="contact_request_channel", native_enum=False)
    )


class Invitation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """docs/DITSALA_MASTER_SPEC.md §22."""

    __tablename__ = "invitations"

    inviter_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    invite_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    channel: Mapped[str] = mapped_column(
        Enum("sms", "link", name="invitation_channel", native_enum=False)
    )
    status: Mapped[str] = mapped_column(
        Enum("sent", "redeemed", "expired", name="invitation_status", native_enum=False),
        default="sent",
        server_default=text("'sent'"),
    )
    redeemed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    # "time-bounded" per §22 — checked application-side; a Postgres CHECK
    # can't reference now() at insert time in a portable way.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Block(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "blocks"
    __table_args__ = (UniqueConstraint("blocker_user_id", "blocked_user_id"),)

    blocker_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    blocked_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    reason: Mapped[str | None] = mapped_column(String(500))


class Report(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "reports"

    reporter_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    reported_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    reason: Mapped[str] = mapped_column(String(1000))
    # Metadata only — never decrypted message content. See §5, §24.
    context_ref: Mapped[str | None] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(
        Enum("open", "reviewed", "actioned", name="report_status", native_enum=False),
        default="open",
        server_default=text("'open'"),
    )
    reviewed_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="SET NULL")
    )
