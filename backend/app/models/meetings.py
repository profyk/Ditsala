"""
Ditsala Meet — docs/DITSALA_MEET_SPEC.md §3. Phase 1 added enough schema
for a real, working meeting (create, join, end) via LiveKit. Phase 2
(this addition) adds waiting-room admission tracking, host-enforced
recording, in-meeting chat, polls, and Q&A — still not modeling every
future phase's tables speculatively (breakout rooms, AI notes,
organizations/billing remain un-modeled until those phases actually
build them). See DITSALA_MEET_SPEC.md §9.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

MEETING_TYPES = ("standard", "webinar", "classroom", "interview", "town_hall", "conference")
MEETING_STATUSES = ("scheduled", "live", "ended", "cancelled")
PARTICIPANT_ROLES = ("host", "co_host", "participant")
# §9 Phase 2 — a participant on a waiting-room-enabled meeting starts
# `waiting` and needs the host/co-host to `admit` them before a LiveKit
# token is ever minted for them; `removed` is a host-enforced kick,
# distinct from `left` (which is just left_at being set — a participant
# leaving on their own is not an admission-status change).
PARTICIPANT_ADMISSION_STATUSES = ("waiting", "admitted", "removed")
# §9 Phase 4 — webinar/town_hall/conference are large-audience modes: a
# joining `participant` (never host/co-host) starts `audience` (a
# view-only LiveKit grant, no `can_publish`) until a host/co-host invites
# them to the stage. Every other meeting type keeps today's behavior —
# `on_stage` for everyone, i.e. unchanged from before this phase.
LARGE_AUDIENCE_MEETING_TYPES = ("webinar", "town_hall", "conference")
PARTICIPANT_STAGE_STATUSES = ("audience", "on_stage")


class Meeting(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "meetings"
    __table_args__ = (
        Index("ix_meetings_title_search", "title_search", postgresql_using="gin"),
    )

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
    # §18 search — a generated, indexed column rather than computing
    # `to_tsvector` at query time on every row scanned.
    title_search: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', title)", persisted=True)
    )


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
    admission_status: Mapped[str] = mapped_column(
        Enum(
            *PARTICIPANT_ADMISSION_STATUSES,
            name="meeting_participant_admission_status",
            native_enum=False,
        ),
        default="admitted",
        server_default=text("'admitted'"),
    )
    stage_status: Mapped[str] = mapped_column(
        Enum(
            *PARTICIPANT_STAGE_STATUSES,
            name="meeting_participant_stage_status",
            native_enum=False,
        ),
        default="on_stage",
        server_default=text("'on_stage'"),
    )


class MeetingRecording(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "meeting_recordings"

    RECORDING_STATUSES = ("processing", "ready", "failed")

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    # LiveKit Egress's own id for this recording job — the handle used to
    # stop it and to correlate the eventual egress-webhook/poll result.
    egress_id: Mapped[str] = mapped_column(String(128), unique=True)
    storage_key: Mapped[str | None] = mapped_column(String(512))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        Enum(*RECORDING_STATUSES, name="meeting_recording_status", native_enum=False),
        default="processing",
        server_default=text("'processing'"),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MeetingMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "meeting_messages"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    sender_participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meeting_participants.id", ondelete="CASCADE")
    )
    # Null means "everyone" — a broadcast message; otherwise a private
    # message to one other participant in the same meeting (§7 chat).
    recipient_participant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meeting_participants.id", ondelete="CASCADE")
    )
    body: Mapped[str] = mapped_column(String(4000))


class MeetingPoll(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "meeting_polls"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    created_by_participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meeting_participants.id", ondelete="CASCADE")
    )
    question: Mapped[str] = mapped_column(String(500))
    # Ordered list of option strings — polls don't need a child table of
    # their own; votes reference an option by its index into this array.
    options: Mapped[list[Any]] = mapped_column(JSONB)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MeetingPollVote(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "meeting_poll_votes"

    poll_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meeting_polls.id", ondelete="CASCADE"), index=True
    )
    voter_participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meeting_participants.id", ondelete="CASCADE")
    )
    option_index: Mapped[int] = mapped_column(Integer)


class MeetingQuestion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "meeting_questions"

    QUESTION_STATUSES = ("open", "answered", "dismissed")

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    asked_by_participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meeting_participants.id", ondelete="CASCADE")
    )
    body: Mapped[str] = mapped_column(String(2000))
    upvote_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    status: Mapped[str] = mapped_column(
        Enum(*QUESTION_STATUSES, name="meeting_question_status", native_enum=False),
        default="open",
        server_default=text("'open'"),
    )
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BreakoutRoom(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "breakout_rooms"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    # Its own, independent LiveKit room — a breakout is a real second SFU
    # room, not a sub-state of the parent room's own `livekit_room_name`.
    livekit_room_name: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BreakoutRoomParticipant(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "breakout_room_participants"

    breakout_room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("breakout_rooms.id", ondelete="CASCADE"), index=True
    )
    participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meeting_participants.id", ondelete="CASCADE")
    )


class MeetingTranscript(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    §9 Phase 3 (DITSALA_MEET_SPEC.md §6). Populated by
    `MeetingIntelligenceService.transcribe_recording` from a finished
    `MeetingRecording` via Deepgram's prerecorded API — not a live,
    per-track stream. See that spec's Phase 3 section for why: a live
    LiveKit Agents worker (joining the room as a hidden participant to
    tap each track in real time) needs native WebRTC bindings this
    resource-constrained dev environment could not safely install, so
    this pass gets the post-meeting transcript/notes/search value
    (§15-18) without live in-meeting captions — a real, disclosed scope
    cut, not a silently faked one. See docs/SECURITY_GAPS.md.
    """

    __tablename__ = "meeting_transcripts"
    __table_args__ = (
        Index(
            "ix_meeting_transcripts_search_vector", "search_vector", postgresql_using="gin"
        ),
    )

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    # Null when Deepgram's diarization couldn't confidently attribute a
    # segment to a speaker index we could map back to a participant.
    speaker_participant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meeting_participants.id", ondelete="SET NULL")
    )
    text_segment: Mapped[str] = mapped_column(String(8000))
    started_at_ms: Mapped[int] = mapped_column(BigInteger)
    ended_at_ms: Mapped[int] = mapped_column(BigInteger)
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', text_segment)", persisted=True)
    )


class MeetingAiNote(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "meeting_ai_notes"

    NOTE_KINDS = ("summary", "decision", "action_item", "question", "topic")

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(
        Enum(*NOTE_KINDS, name="meeting_ai_note_kind", native_enum=False)
    )
    content: Mapped[str] = mapped_column(String(4000))
    # §15 "allow users to edit" — null until a participant has actually
    # edited the AI-generated text; distinguishes an untouched AI note
    # from a human-corrected one without a separate boolean flag.
    edited_by_participant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meeting_participants.id", ondelete="SET NULL")
    )


class MeetingRegistration(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """§9 Phase 4 — webinar/conference RSVP tracking, deliberately not
    auth-gated (a public webinar invite shouldn't require a DITSALA
    account to register interest — same reasoning as guest join, §35).
    `attended_at` is set best-effort when a join/guest-join's email
    matches an existing registration; it's headcount tracking, not an
    admission gate — waiting room / lock still govern actual entry."""

    __tablename__ = "meeting_registrations"
    __table_args__ = (
        UniqueConstraint(
            "meeting_id", "email", name="uq_meeting_registrations_meeting_id_email"
        ),
    )

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str] = mapped_column(String(120))
    # Set only when the registrant later joins with a DITSALA account —
    # never required at registration time.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    attended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
