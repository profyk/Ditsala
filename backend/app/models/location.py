import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class LocationShare(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "location_shares"

    sharer_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # Must be `trusted` tier — enforced in the domain layer (Phase 6), not
    # just here; the DB doesn't cross-reference contacts.tier via FK.
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LocationPing(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """P2 — see §5. Retention: share duration + 24h, or 90d if SOS-linked (§34.2)."""

    __tablename__ = "location_pings"

    location_share_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("location_shares.id", ondelete="CASCADE"), index=True
    )
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    accuracy_m: Mapped[float] = mapped_column(Float)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class LocationAccessLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Transparency log — §25: 'who viewed your location'."""

    __tablename__ = "location_access_log"

    location_share_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("location_shares.id", ondelete="CASCADE"), index=True
    )
    accessed_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    accessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SosEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """docs/DITSALA_MASTER_SPEC.md §26. Lawful basis: POPIA §11(1)(d)."""

    __tablename__ = "sos_events"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cancel_window_seconds: Mapped[int] = mapped_column(
        Integer, default=10, server_default=text("10")
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        Enum(
            "armed", "cancelled", "escalated", "resolved",
            name="sos_event_status", native_enum=False,
        ),
        default="armed",
        server_default=text("'armed'"),
    )
    last_known_location_ref: Mapped[str | None] = mapped_column(String(256))


class SosNotification(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "sos_notifications"

    sos_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sos_events.id", ondelete="CASCADE"), index=True
    )
    notified_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    notified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    channel: Mapped[str] = mapped_column(
        Enum("push", "sms", name="sos_notification_channel", native_enum=False)
    )
