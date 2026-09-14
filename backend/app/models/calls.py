import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Call(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "calls"

    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL")
    )
    initiator_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(Enum("voice", "video", name="call_type", native_enum=False))
    status: Mapped[str] = mapped_column(
        Enum(
            "ringing", "active", "ended", "missed", "declined",
            name="call_status", native_enum=False,
        ),
        default="ringing",
        server_default=text("'ringing'"),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CallParticipant(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "call_participants"

    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ice_relay_used: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
