"""
Ditsala VIP — AI-powered multilingual communication. `vip_messages`/
`vip_message_translations` deliberately do NOT reuse `messages` (see
`models/messaging.py`'s `Conversation.type` docstring): translation needs
server-readable plaintext, `messages.ciphertext` is opaque by design.
`translation_requests` is the generic job/result table shared by VIP chat,
the AI Interpreter, and on-demand conference-chat translation — one row
per translation attempt, `status` driving pending -> processing ->
completed/failed, no separate "results" table (a request row *is* its own
result once completed).
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

TRANSLATION_STATUSES = ("pending", "processing", "completed", "failed")
TRANSLATION_CONTEXT_TYPES = ("vip_message", "interpreter", "conference_caption")


class UserLanguagePreference(Base):
    """One row per user (upserted, like `SystemConfig`) — §3/§4 of the VIP
    spec: "the user should be able to choose their preferred language
    independently from the other person's language.\""""

    __tablename__ = "user_language_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    preferred_language: Mapped[str] = mapped_column(String(16))
    auto_detect_language: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    translate_incoming: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    translate_outgoing: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class VipMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A VIP multilingual chat message — plaintext at rest, by disclosed
    design (see this module's docstring). Structurally mirrors `Message`
    minus the E2EE columns."""

    __tablename__ = "vip_messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    sender_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    client_message_id: Mapped[str] = mapped_column(String(128), unique=True)
    original_text: Mapped[str] = mapped_column(String(4000))
    original_language: Mapped[str] = mapped_column(String(16))
    reply_to_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vip_messages.id", ondelete="SET NULL")
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VipMessageTranslation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One row per target language a `VipMessage` needs — today that's
    always exactly one (the other 1:1 participant's language); the shape
    already supports a future group thread needing several."""

    __tablename__ = "vip_message_translations"

    vip_message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vip_messages.id", ondelete="CASCADE"), index=True
    )
    target_language: Mapped[str] = mapped_column(String(16))
    translated_text: Mapped[str | None] = mapped_column(String(4000))
    provider: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(
        Enum(*TRANSLATION_STATUSES, name="translation_status", native_enum=False),
        default="pending",
        server_default=text("'pending'"),
    )
    error_message: Mapped[str | None] = mapped_column(String(500))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TranslationRequest(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """The generic translation job/result — every call into
    `TranslationService.translate_and_record` writes one of these,
    regardless of caller (VIP chat, AI Interpreter, on-demand conference
    chat translation). `context_id` is deliberately not a hard FK: which
    table it points into depends on `context_type`."""

    __tablename__ = "translation_requests"

    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    context_type: Mapped[str] = mapped_column(
        Enum(*TRANSLATION_CONTEXT_TYPES, name="translation_context_type", native_enum=False)
    )
    context_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    source_text: Mapped[str] = mapped_column(String(4000))
    # Null means "auto-detect" — resolved language is written back once known.
    source_language: Mapped[str | None] = mapped_column(String(16))
    target_language: Mapped[str] = mapped_column(String(16))
    provider: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(
        Enum(*TRANSLATION_STATUSES, name="translation_status", native_enum=False),
        default="pending",
        server_default=text("'pending'"),
    )
    translated_text: Mapped[str | None] = mapped_column(String(4000))
    error_message: Mapped[str | None] = mapped_column(String(500))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InterpreterSession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Groups AI Interpreter turns for the screen's recent-history view —
    each turn is a `TranslationRequest` with `context_type="interpreter"`,
    `context_id=<this session's id>`."""

    __tablename__ = "interpreter_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    my_language: Mapped[str] = mapped_column(String(16))
    other_language: Mapped[str] = mapped_column(String(16))


class ConferenceLanguagePreference(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Which language a meeting participant wants (§8 of the VIP spec) —
    additive-only, doesn't touch `meeting_participants` itself."""

    __tablename__ = "conference_language_preferences"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meeting_participants.id", ondelete="CASCADE"),
        unique=True,
    )
    language: Mapped[str] = mapped_column(String(16))


class TranslationUsage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A daily per-user rollup, incremented alongside every
    `TranslationRequest` write — the admin usage/cost dashboard reads this
    instead of scanning the full requests table."""

    __tablename__ = "translation_usage"
    __table_args__ = (
        UniqueConstraint("user_id", "usage_date", name="uq_translation_usage_user_date"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    usage_date: Mapped[date] = mapped_column(Date)
    request_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    character_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
