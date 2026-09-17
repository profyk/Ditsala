import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, LargeBinary, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Conversation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "conversations"

    type: Mapped[str] = mapped_column(
        Enum("direct", "group", name="conversation_type", native_enum=False)
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    disappearing_timer_seconds: Mapped[int | None] = mapped_column(Integer)
    # Group display name — null for `direct` (the client shows the other
    # member instead). Plaintext, not E2EE: like Signal's own older group
    # names, this is treated as low-sensitivity metadata, not message
    # content — a real, disclosed scope line, not an oversight.
    title: Mapped[str | None] = mapped_column(String(200))


class ConversationMember(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "conversation_members"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(
        Enum("member", "admin", name="conversation_member_role", native_enum=False),
        default="member",
        server_default=text("'member'"),
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    muted_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Message(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    sender_device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="SET NULL"), nullable=True
    )
    # P2 — opaque ciphertext, server never has plaintext. See §6, §7.
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    content_type: Mapped[str] = mapped_column(
        Enum(
            "text", "media", "voice_note", "reaction", "system",
            name="message_content_type", native_enum=False,
        )
    )
    client_message_id: Mapped[str] = mapped_column(String(128), unique=True)
    # Added in Phase 4 (spec's messaging feature list includes replies,
    # which §4's original table list didn't carry a column for).
    reply_to_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL")
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MessageReceipt(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "message_receipts"

    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(
        Enum("delivered", "read", name="message_receipt_status", native_enum=False)
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MediaObject(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "media_objects"

    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    # P2 — pointer to a client-encrypted blob; backend never has the key.
    s3_key: Mapped[str] = mapped_column(String(512))
    encrypted_size_bytes: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(128))
    client_side_encrypted: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
