import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, LargeBinary, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Conversation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "conversations"

    # "vip_multilingual" added for Ditsala VIP (docs/DITSALA_VIP_SPEC.md) —
    # a deliberately separate, NOT end-to-end-encrypted conversation kind:
    # AI translation requires the backend to read plaintext, which is
    # structurally incompatible with `messages.ciphertext` being opaque by
    # design (§7.3). Reusing this table/`conversation_members` for VIP
    # multilingual chat membership is real reuse; the message *content*
    # lives in a new `vip_messages` table instead of `messages` for exactly
    # that reason — see `app/models/translation.py`.
    type: Mapped[str] = mapped_column(
        Enum(
            "direct", "group", "vip_multilingual",
            name="conversation_type", native_enum=False, length=32,
        )
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
            "text", "media", "voice_note", "reaction", "system", "contact",
            name="message_content_type", native_enum=False,
        )
    )
    client_message_id: Mapped[str] = mapped_column(String(128), unique=True)
    # Added in Phase 4 (spec's messaging feature list includes replies,
    # which §4's original table list didn't carry a column for).
    reply_to_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL")
    )
    # Denormalized alongside MediaObject.message_id (the direction the
    # access-control check in get_media_download_url actually needs) —
    # real gap this closes: MessageResponse had no way to tell a
    # recipient which MediaObject a media/voice_note message points to,
    # since the only link was MediaObject -> Message, never the reverse.
    # Set once, at send_message time, alongside the other direction.
    # `use_alter=True` because this creates a genuine circular FK with
    # MediaObject.message_id below — without it, SQLAlchemy can't
    # topologically sort the two tables' creation order (a real
    # SAWarning, not cosmetic), so this one is deferred to its own
    # ALTER TABLE rather than being inlined on CREATE TABLE.
    media_object_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "media_objects.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_messages_media_object_id",
        ),
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Per-message pin (distinct from ConversationMember.pinned_at, which
    # pins a whole *conversation* in a member's own list) — a banner
    # shows whichever pinned message has the latest pinned_at, see
    # MessageRepository.get_pinned_for_conversation.
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set at send_message time when the sender is relaying a message they
    # decrypted elsewhere — purely a display flag ("Forwarded"). Forwarding
    # itself is a client-side operation (decrypt, then send fresh
    # ciphertext per target conversation's own Sender Key) since ciphertext
    # from one conversation is never valid in another.
    is_forwarded: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


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
    # Who requested this upload — real gap found and closed alongside
    # wiring up the media-message UI: nothing ever linked a MediaObject
    # to the message that sends it (message_id stayed null forever), and
    # get_media_download_url's own membership check only runs when
    # message_id is set — so every uploaded object was silently
    # downloadable by any authenticated user who learned its id. This
    # column lets send_message verify the linking caller actually
    # requested this specific upload before attaching it to their
    # message (see MessagingService.send_message).
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # P2 — pointer to a client-encrypted blob; backend never has the key.
    s3_key: Mapped[str] = mapped_column(String(512))
    encrypted_size_bytes: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(128))
    client_side_encrypted: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
