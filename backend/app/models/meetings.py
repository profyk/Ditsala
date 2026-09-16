"""
Ditsala Meet — docs/DITSALA_MEET_SPEC.md §3. Phase 1 slice only: enough
schema for a real, working meeting (create, join, end) via LiveKit.
Later phases (recording, chat, polls, Q&A, AI notes, breakout rooms,
organizations/billing) add their own tables when those phases actually
build them — not modeled speculatively ahead of time, unlike the parent
DITSALA schema's Phase 1 (which had the luxury of a fully-settled spec
before any code). See DITSALA_MEET_SPEC.md §9.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

MEETING_TYPES = ("standard", "webinar", "classroom", "interview", "town_hall", "conference")
MEETING_STATUSES = ("scheduled", "live", "ended", "cancelled")
PARTICIPANT_ROLES = ("host", "co_host", "participant")


class Meeting(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "meetings"

    host_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # The LiveKit room's own identifier — unique per meeting, opaque, safe
    # to hand to LiveKit's API; never used as a guessable join secret on
    # its own (see the join flow's password/waiting-room checks instead).
    livekit_room_name: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    meeting_type: Mapped[str] = mapped_column(
        Enum(*MEETING_TYPES, name="meeting_type", native_enum=False, validate_strings=True),
        default="standard",
        server_default=text("'standard'"),
    )
    status: Mapped[str] = mapped_column(
        Enum(*MEETING_STATUSES, name="meeting_status", native_enum=False, validate_strings=True),
        default="scheduled",
        server_default=text("'scheduled'"),
    )
    scheduled_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_duration_minutes: Mapped[int | None] = mapped_column(Integer)
    actual_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # P0-equivalent — Argon2id, same treatment as users.ditsala_code_hash.
    password_hash: Mapped[str | None] = mapped_column(String(256))
    waiting_room_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MeetingParticipant(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "meeting_participants"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    # Null means a guest (§35) — no DITSALA account exists for this row.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    guest_display_name: Mapped[str | None] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(
        Enum(*PARTICIPANT_ROLES, name="meeting_participant_role", native_enum=False),
        default="participant",
        server_default=text("'participant'"),
    )
    # The identity string handed to LiveKit for this participant's token —
    # stable per (meeting, participant) so a reconnect re-joins as the same
    # LiveKit participant rather than a duplicate.
    livekit_participant_identity: Mapped[str] = mapped_column(String(128))
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
