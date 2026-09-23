"""
Ditsala Meet — docs/DITSALA_MEET_SPEC.md §4, §7, §9. Phase 1 covered
create/join/end. Phase 2 (this file) adds waiting-room admission,
host/co-host controls, recording, reactions/raise-hand, chat, polls,
and Q&A — LiveKit (via `RoomProvider`) remains the SFU; this service
still never touches media itself.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.security import hash_secret, verify_secret
from app.domain.billing.conference_plans import TOOL_ANALYTICS, TOOL_BREAKOUT_ROOMS, TOOL_RECORDING
from app.domain.billing.plans import PlanService
from app.domain.meetings.analytics import MeetingAnalyticsReport, build_meeting_analytics
from app.domain.meetings.entitlements import (
    clamp_duration_minutes,
    count_active_participants,
    guest_capacity_exceeded,
    has_tool,
    resolve_conference_entitlements,
    total_minutes_exceeds_cap,
)
from app.domain.meetings.interfaces import RecordingHandle, RoomAccessToken, RoomProvider
from app.domain.messaging.interfaces import StorageProvider
from app.domain.translation.service import TranslationService
from app.models.accounts import User
from app.models.meetings import (
    LARGE_AUDIENCE_MEETING_TYPES,
    BreakoutRoom,
    BreakoutRoomParticipant,
    Meeting,
    MeetingDocument,
    MeetingMessage,
    MeetingParticipant,
    MeetingPoll,
    MeetingPollVote,
    MeetingQuestion,
    MeetingRecording,
    MeetingRegistration,
)
from app.models.translation import ConferenceLanguagePreference, TranslationRequest
from app.repositories.meetings import (
    BreakoutRoomParticipantRepository,
    BreakoutRoomRepository,
    MeetingDocumentRepository,
    MeetingMessageRepository,
    MeetingParticipantRepository,
    MeetingPollRepository,
    MeetingPollVoteRepository,
    MeetingQuestionRepository,
    MeetingRecordingRepository,
    MeetingRegistrationRepository,
    MeetingRepository,
)
from app.repositories.translation import ConferenceLanguagePreferenceRepository
from app.repositories.users import UserRepository

MAX_MEETING_DOCUMENT_SIZE_BYTES = 50 * 1024 * 1024  # 50MB

_HOST_ROLES = ("host", "co_host")
ROOM_PHASES = ("scheduled", "prep", "live", "ended")
DEFAULT_PREP_LEAD_MINUTES = 15


def _initial_stage_status(meeting: Meeting, role: str) -> str:
    if role in _HOST_ROLES:
        return "on_stage"
    if meeting.meeting_type in LARGE_AUDIENCE_MEETING_TYPES:
        return "audience"
    return "on_stage"


def _is_within_join_window(meeting: Meeting) -> bool:
    """§9 Phase 4 / Conference Room `prep` — a shared meeting link's
    recipient shouldn't be let straight into an empty room hours before a
    scheduled call; a non-host may join (and sit in `waiting`, per the
    Conference Room kickoff prompt) starting `prep_lead_minutes` before
    `scheduled_start_at`, the same window the room's own `prep` phase
    opens in (`get_room_phase`) — one config value, not two."""
    if meeting.status != "scheduled" or meeting.scheduled_start_at is None:
        return True
    earliest_join_at = meeting.scheduled_start_at - timedelta(minutes=meeting.prep_lead_minutes)
    return datetime.now(UTC) >= earliest_join_at


def get_room_phase(meeting: Meeting) -> str:
    """Conference Room kickoff prompt's `scheduled|prep|live|ended` — derived
    from existing timestamps/status rather than stored as its own
    `MEETING_STATUSES` value, same "compute it" approach
    `_is_within_join_window` already used for the join-window check."""
    if meeting.status in ("ended", "cancelled"):
        return "ended"
    if meeting.status == "live":
        return "live"
    if meeting.scheduled_start_at is not None and _is_within_join_window(meeting):
        return "prep"
    return "scheduled"


def get_live_deadline(meeting: Meeting) -> datetime | None:
    """The countdown target a host/co-host UI polls — `None` until the
    meeting is actually live or has no planned duration. Per the kickoff
    prompt's confirmed decision, reaching this deadline does NOT auto-end
    the meeting (`end_meeting` stays the only thing that does) — a host
    UI alerts and offers Extend/End; this value is what it counts down to
    and re-reads after an extension."""
    if meeting.actual_start_at is None or meeting.scheduled_duration_minutes is None:
        return None
    total_minutes = meeting.scheduled_duration_minutes + meeting.duration_extended_minutes
    return meeting.actual_start_at + timedelta(minutes=total_minutes)


class MeetingError(Exception):
    """Raised for meeting preconditions a caller should turn into a 4xx, not a 500."""


@dataclass(frozen=True)
class JoinResult:
    meeting: Meeting
    participant: MeetingParticipant
    # None while the participant is still in the waiting room — no
    # LiveKit token is minted until a host/co-host admits them, so a
    # waiting participant never receives real room-join credentials.
    access_token: RoomAccessToken | None


@dataclass(frozen=True)
class JoinInfo:
    """§9 Phase 4 — what a shared meeting link's recipient needs to know
    *before* attempting to join: whether a password is required, and
    whether it's too early relative to a scheduled start time. Exposed
    over a public, unauthenticated endpoint (never includes the password
    hash or anything else sensitive) so a client can show "this meeting
    is scheduled for X" or a password prompt without first requiring a
    DITSALA login."""

    meeting: Meeting
    requires_password: bool
    joinable_now: bool
    room_phase: str
    live_deadline_at: datetime | None


@dataclass(frozen=True)
class PollResults:
    poll: MeetingPoll
    # option index -> vote count, always covering every option (0 for
    # options nobody voted for) so a client never has to special-case a
    # missing key.
    counts: dict[int, int]


class MeetingService:
    def __init__(
        self,
        *,
        meetings: MeetingRepository,
        participants: MeetingParticipantRepository,
        room_provider: RoomProvider,
        recordings: MeetingRecordingRepository,
        messages: MeetingMessageRepository,
        polls: MeetingPollRepository,
        poll_votes: MeetingPollVoteRepository,
        questions: MeetingQuestionRepository,
        breakout_rooms: BreakoutRoomRepository,
        breakout_room_participants: BreakoutRoomParticipantRepository,
        registrations: MeetingRegistrationRepository,
        documents: MeetingDocumentRepository,
        storage_provider: StorageProvider,
        conference_language_preferences: ConferenceLanguagePreferenceRepository,
        translation_service: TranslationService,
        users: UserRepository,
        # Optional — Conference Room plan enforcement (guest cap, duration
        # cap, tool gating; see app/domain/meetings/entitlements.py).
        # Every existing test constructs this service without it, and
        # `entitlements.resolve_conference_entitlements` degrades to
        # unlimited/every-tool-on when it's `None`, so leaving it unwired
        # anywhere (a test, a future call site) is a safe no-op rather
        # than a crash — enforcement only actually applies where
        # `app/api/v1/deps.py` wires a real `PlanService` in.
        plans: PlanService | None = None,
    ) -> None:
        self._meetings = meetings
        self._participants = participants
        self._room_provider = room_provider
        self._recordings = recordings
        self._messages = messages
        self._polls = polls
        self._poll_votes = poll_votes
        self._questions = questions
        self._breakout_rooms = breakout_rooms
        self._breakout_room_participants = breakout_room_participants
        self._registrations = registrations
        self._documents = documents
        self._storage = storage_provider
        self._conference_language_preferences = conference_language_preferences
        self._translation = translation_service
        self._users = users
        self._plans = plans

    # ---- Phase 1: create / join / end -----------------------------------

    async def create_meeting(
        self,
        *,
        host: User,
        title: str,
        meeting_type: str = "standard",
        scheduled_start_at: datetime | None = None,
        scheduled_duration_minutes: int | None = None,
        password: str | None = None,
        waiting_room_enabled: bool = False,
        prep_lead_minutes: int = DEFAULT_PREP_LEAD_MINUTES,
    ) -> Meeting:
        # Conference Room plan enforcement — clamp the requested duration
        # to the host's plan cap and snapshot their guest limit onto the
        # meeting itself (see `Meeting.max_participants`'s docstring for
        # why it's snapshotted rather than re-read live).
        entitlements = await resolve_conference_entitlements(self._plans, host)
        meeting = await self._meetings.add(
            Meeting(
                host_user_id=host.id,
                livekit_room_name=f"meet-{uuid.uuid4().hex}",
                title=title,
                meeting_type=meeting_type,
                scheduled_start_at=scheduled_start_at,
                scheduled_duration_minutes=clamp_duration_minutes(
                    scheduled_duration_minutes, entitlements
                ),
                password_hash=hash_secret(password) if password else None,
                waiting_room_enabled=waiting_room_enabled,
                prep_lead_minutes=prep_lead_minutes,
                max_participants=entitlements.max_guests,
            )
        )
        await self._participants.add(
            MeetingParticipant(
                meeting_id=meeting.id,
                user_id=host.id,
                role="host",
                livekit_participant_identity=str(host.id),
                admission_status="admitted",
            )
        )
        return meeting

    async def get_participant_for_user(
        self, *, meeting_id: uuid.UUID, user_id: uuid.UUID
    ) -> MeetingParticipant | None:
        return await self._participants.get_by_meeting_and_user(meeting_id, user_id)

    async def get_meeting(self, meeting_id: uuid.UUID) -> Meeting:
        meeting = await self._meetings.get(meeting_id)
        if meeting is None:
            raise MeetingError("No such meeting.")
        return meeting

    async def list_hosted_meetings(self, host_user_id: uuid.UUID) -> list[Meeting]:
        return await self._meetings.list_for_host(host_user_id)

    async def join(
        self, *, meeting_id: uuid.UUID, user: User, password: str | None = None
    ) -> JoinResult:
        meeting = await self.get_meeting(meeting_id)
        is_host = meeting.host_user_id == user.id
        self._check_joinable(meeting, password=password, is_host=is_host)

        participant = await self._participants.get_by_meeting_and_user(meeting_id, user.id)
        if participant is None:
            role = "host" if is_host else "participant"
            if not is_host:
                await self._check_guest_capacity(meeting)
            needs_admission = meeting.waiting_room_enabled and role == "participant"
            participant = await self._participants.add(
                MeetingParticipant(
                    meeting_id=meeting_id,
                    user_id=user.id,
                    role=role,
                    livekit_participant_identity=str(user.id),
                    admission_status="waiting" if needs_admission else "admitted",
                    stage_status=_initial_stage_status(meeting, role),
                )
            )
            if user.email is not None:
                await self._mark_attended(meeting_id, user.email)
        if participant.admission_status == "removed":
            raise MeetingError("You have been removed from this meeting.")
        if participant.admission_status == "waiting":
            return JoinResult(meeting=meeting, participant=participant, access_token=None)

        participant.joined_at = datetime.now(UTC)
        participant.left_at = None
        self._mark_live_if_needed(meeting)

        token = self._room_provider.create_access_token(
            room_name=meeting.livekit_room_name,
            participant_identity=participant.livekit_participant_identity,
            participant_name=user.display_name,
            is_host=participant.role in _HOST_ROLES,
            can_publish=participant.stage_status == "on_stage",
        )
        return JoinResult(meeting=meeting, participant=participant, access_token=token)

    async def guest_join(
        self,
        *,
        meeting_id: uuid.UUID,
        guest_display_name: str,
        password: str | None = None,
        guest_email: str | None = None,
    ) -> JoinResult:
        """§35 — no DITSALA account required or created; `user_id` stays
        null on the participant row, matching the model's own nullable
        design for exactly this case. `guest_email` is optional and used
        only to best-effort mark a matching §9 Phase 4 registration as
        attended — never required to join."""
        meeting = await self.get_meeting(meeting_id)
        self._check_joinable(meeting, password=password, is_host=False)
        await self._check_guest_capacity(meeting)

        needs_admission = meeting.waiting_room_enabled
        guest_identity = f"guest-{uuid.uuid4().hex}"
        participant = await self._participants.add(
            MeetingParticipant(
                meeting_id=meeting_id,
                user_id=None,
                guest_display_name=guest_display_name,
                role="participant",
                livekit_participant_identity=guest_identity,
                admission_status="waiting" if needs_admission else "admitted",
                stage_status=_initial_stage_status(meeting, "participant"),
                joined_at=None if needs_admission else datetime.now(UTC),
            )
        )
        if guest_email:
            await self._mark_attended(meeting_id, guest_email)
        if needs_admission:
            return JoinResult(meeting=meeting, participant=participant, access_token=None)

        self._mark_live_if_needed(meeting)
        token = self._room_provider.create_access_token(
            room_name=meeting.livekit_room_name,
            participant_identity=guest_identity,
            participant_name=guest_display_name,
            is_host=False,
            can_publish=participant.stage_status == "on_stage",
        )
        return JoinResult(meeting=meeting, participant=participant, access_token=token)

    async def _mark_attended(self, meeting_id: uuid.UUID, email: str) -> None:
        registration = await self._registrations.get_by_meeting_and_email(meeting_id, email)
        if registration is not None and registration.attended_at is None:
            registration.attended_at = datetime.now(UTC)

    async def get_participant_status(
        self, *, meeting_id: uuid.UUID, participant_id: uuid.UUID
    ) -> JoinResult:
        """
        §9 Phase 2/4 — lets a waiting participant's client poll for
        admission without re-calling `join`/`guest_join` (which, for a
        guest, would mint a brand-new participant row every poll rather
        than checking the existing one). Deliberately public/unauthenticated
        the same way `guest_join` already is: knowing a `participant_id`
        (an unguessable UUID) is already the entire trust boundary for a
        guest's access token today, so this adds no new class of exposure.
        """
        meeting = await self.get_meeting(meeting_id)
        participant = await self._get_participant_in_meeting(meeting_id, participant_id)
        if participant.admission_status == "removed":
            raise MeetingError("You have been removed from this meeting.")
        if participant.admission_status == "waiting":
            return JoinResult(meeting=meeting, participant=participant, access_token=None)

        participant_name = participant.guest_display_name or str(participant.user_id)
        token = self._room_provider.create_access_token(
            room_name=meeting.livekit_room_name,
            participant_identity=participant.livekit_participant_identity,
            participant_name=participant_name,
            is_host=participant.role in _HOST_ROLES,
            can_publish=participant.stage_status == "on_stage",
        )
        return JoinResult(meeting=meeting, participant=participant, access_token=token)

    async def leave(self, *, meeting_id: uuid.UUID, user_id: uuid.UUID) -> None:
        participant = await self._participants.get_by_meeting_and_user(meeting_id, user_id)
        if participant is not None:
            participant.left_at = datetime.now(UTC)

    async def end_meeting(self, *, meeting_id: uuid.UUID, acting_user_id: uuid.UUID) -> Meeting:
        meeting = await self.get_meeting(meeting_id)
        if meeting.host_user_id != acting_user_id:
            raise MeetingError("Only the host can end this meeting.")
        if meeting.status == "ended":
            return meeting
        meeting.status = "ended"
        meeting.actual_end_at = datetime.now(UTC)
        return meeting

    async def extend_duration(
        self, *, meeting_id: uuid.UUID, acting_user_id: uuid.UUID, additional_minutes: int
    ) -> Meeting:
        """Host or co-host, any time during a live meeting — per the
        kickoff prompt's confirmed decision, the countdown never
        auto-ends the meeting on its own, so this just pushes the
        deadline `get_live_deadline` computes further out."""
        await self._require_host_or_cohost(meeting_id, acting_user_id)
        if additional_minutes <= 0:
            raise MeetingError("additional_minutes must be positive.")
        meeting = await self.get_meeting(meeting_id)
        if meeting.status != "live":
            raise MeetingError("Can only extend a meeting that is currently live.")
        if meeting.scheduled_duration_minutes is not None:
            host = await self._users.get(meeting.host_user_id)
            entitlements = await resolve_conference_entitlements(self._plans, host)
            projected_total = (
                meeting.scheduled_duration_minutes
                + meeting.duration_extended_minutes
                + additional_minutes
            )
            if total_minutes_exceeds_cap(projected_total, entitlements):
                raise MeetingError(
                    "This extension would exceed the host's Conference plan's "
                    "maximum meeting duration."
                )
        meeting.duration_extended_minutes += additional_minutes
        return meeting

    # ---- admin governance (app/domain/admin/meetings_governance.py) -------
    # No host/co-host check and no plan-cap check — deliberately: an admin
    # overriding a live meeting is, by definition, not bound by the host's
    # own plan limits (that's the point of an override), and authorization
    # already happened at the admin router layer (RBAC's `require_permission`,
    # same as every other `AdminService` mutation) rather than being
    # re-checked here. Never called from the public /meetings router.

    async def admin_extend_duration(
        self, *, meeting_id: uuid.UUID, additional_minutes: int
    ) -> Meeting:
        if additional_minutes <= 0:
            raise MeetingError("additional_minutes must be positive.")
        meeting = await self.get_meeting(meeting_id)
        if meeting.status != "live":
            raise MeetingError("Can only extend a meeting that is currently live.")
        meeting.duration_extended_minutes += additional_minutes
        return meeting

    async def admin_end_meeting(self, *, meeting_id: uuid.UUID) -> Meeting:
        meeting = await self.get_meeting(meeting_id)
        if meeting.status == "ended":
            return meeting
        meeting.status = "ended"
        meeting.actual_end_at = datetime.now(UTC)
        return meeting

    async def delete_meeting(self, *, meeting_id: uuid.UUID, acting_user_id: uuid.UUID) -> None:
        """Host-only, any status, any time — every meeting-scoped child
        table (`meeting_participants`, `meeting_messages`, recordings,
        polls, documents, transcripts, breakout rooms, registrations,
        conference language preferences) already has `ondelete=CASCADE`
        back to `meetings.id`, so one DELETE is the whole operation, same
        reasoning as the user hard-delete cascade (ADR 0009). Disclosed
        scope cut, matching the existing one for a single document delete:
        this removes the DB rows only, not any underlying storage objects
        (recordings, uploaded documents) — `StorageProvider` has no delete
        method yet."""
        meeting = await self.get_meeting(meeting_id)
        if meeting.host_user_id != acting_user_id:
            raise MeetingError("Only the host can delete this meeting.")
        await self._meetings.delete(meeting)

    async def invite_co_host(
        self, *, meeting_id: uuid.UUID, acting_user_id: uuid.UUID, invitee_phone: str
    ) -> MeetingParticipant:
        """Host-only — pre-provisions a `co_host` participant row for a
        real DITSALA user, found by phone. `join()` already checks for an
        existing participant row before creating one, so when this person
        actually joins (or is already in the meeting), they land as
        `co_host` rather than a plain participant — no separate
        "accept invite" step exists yet; the invited person just has
        elevated access the moment they join, same as being promoted
        in-call already worked (`promote_co_host`)."""
        meeting = await self.get_meeting(meeting_id)
        if meeting.host_user_id != acting_user_id:
            raise MeetingError("Only the host can invite a co-host.")
        invitee = await self._users.get_by_phone(invitee_phone)
        if invitee is None:
            raise MeetingError("No DITSALA account found for that phone number.")
        if invitee.id == meeting.host_user_id:
            raise MeetingError("The host is already hosting this meeting.")
        existing = await self._participants.get_by_meeting_and_user(meeting_id, invitee.id)
        if existing is not None:
            existing.role = "co_host"
            return existing
        return await self._participants.add(
            MeetingParticipant(
                meeting_id=meeting_id,
                user_id=invitee.id,
                role="co_host",
                livekit_participant_identity=str(invitee.id),
                admission_status="admitted",
                stage_status=_initial_stage_status(meeting, "co_host"),
            )
        )

    def _check_joinable(self, meeting: Meeting, *, password: str | None, is_host: bool) -> None:
        if meeting.status in ("ended", "cancelled"):
            raise MeetingError(f"Cannot join a meeting that has {meeting.status}.")
        if meeting.locked_at is not None:
            raise MeetingError("This meeting is locked.")
        # The host doesn't need their own meeting's password — the password
        # gates strangers, and `is_host` here already means
        # `meeting.host_user_id == user.id`, a stronger check. Previously this
        # was unconditional, which meant an authenticated host calling
        # POST /join on their own meeting was rejected unless they also typed
        # the password back in — a real bug, just never exercised (no client
        # called authenticated `/join` before the host-link flow this fixes).
        if not is_host and meeting.password_hash is not None:
            if password is None or not verify_secret(meeting.password_hash, password):
                raise MeetingError("Incorrect meeting password.")
        if not is_host and not _is_within_join_window(meeting):
            raise MeetingError(
                "This meeting hasn't started yet — scheduled for "
                f"{meeting.scheduled_start_at.isoformat()}."  # type: ignore[union-attr]
            )

    async def _check_guest_capacity(self, meeting: Meeting) -> None:
        """Enforced against `meeting.max_participants` (the cap
        snapshotted from the host's plan at `create_meeting` time — see
        that field's docstring), not a freshly-resolved entitlement, so
        a host who downgrades mid-meeting doesn't retroactively strand
        already-admitted participants below a new, lower cap. The host
        themself is never subject to this (see both call sites)."""
        current = count_active_participants(
            await self._participants.list_for_meeting(meeting.id)
        )
        if guest_capacity_exceeded(current, meeting.max_participants):
            raise MeetingError(
                "This meeting has reached the guest limit for the host's Conference plan."
            )

    async def _require_tool(self, meeting: Meeting, tool_id: str, label: str) -> None:
        """Gate a Conference Room feature behind the host's plan. Always
        resolved against the *host's* current plan (not the acting
        co-host's, and not a snapshot — unlike the guest-count cap, a
        tool becoming available mid-meeting via a plan upgrade should
        work immediately, so this re-reads live rather than using a
        column on `Meeting`)."""
        host = await self._users.get(meeting.host_user_id)
        entitlements = await resolve_conference_entitlements(self._plans, host)
        if not has_tool(entitlements, tool_id):
            raise MeetingError(f"{label} is not included in the host's Conference plan.")

    async def get_meeting_analytics(
        self, *, meeting_id: uuid.UUID, acting_user_id: uuid.UUID
    ) -> MeetingAnalyticsReport:
        """Host/co-host only, Premium+/Enterprise (`conference.tools`
        includes `"analytics"`) — attendance duration, unique/guest
        headcount, and real peak-concurrency, computed from data every
        meeting already records. See `app/domain/meetings/analytics.py`."""
        await self._require_host_or_cohost(meeting_id, acting_user_id)
        meeting = await self.get_meeting(meeting_id)
        await self._require_tool(meeting, TOOL_ANALYTICS, "Meeting analytics")
        participants = await self._participants.list_for_meeting(meeting_id)
        return build_meeting_analytics(
            meeting_id=meeting_id, participants=participants, as_of=datetime.now(UTC)
        )

    async def get_join_info(self, meeting_id: uuid.UUID) -> JoinInfo:
        meeting = await self.get_meeting(meeting_id)
        return JoinInfo(
            meeting=meeting,
            requires_password=meeting.password_hash is not None,
            joinable_now=(
                meeting.status not in ("ended", "cancelled")
                and meeting.locked_at is None
                and _is_within_join_window(meeting)
            ),
            room_phase=get_room_phase(meeting),
            live_deadline_at=get_live_deadline(meeting),
        )

    def _mark_live_if_needed(self, meeting: Meeting) -> None:
        if meeting.status == "scheduled":
            meeting.status = "live"
            meeting.actual_start_at = datetime.now(UTC)

    # ---- Phase 2: waiting room -------------------------------------------

    async def list_waiting_participants(
        self, *, meeting_id: uuid.UUID, acting_user_id: uuid.UUID
    ) -> list[MeetingParticipant]:
        await self._require_host_or_cohost(meeting_id, acting_user_id)
        return await self._participants.list_waiting(meeting_id)

    async def list_participants(
        self, *, meeting_id: uuid.UUID, acting_user_id: uuid.UUID
    ) -> list[MeetingParticipant]:
        """Every participant (any admission status) — host/co-host only,
        same reasoning as `list_waiting_participants`. Backs a
        moderation-style "who's in this meeting" panel (mute/remove/
        promote), which — unlike LiveKit's own connected-participant list
        — needs each row's backend `MeetingParticipant.id`, the id those
        actions are keyed on."""
        await self._require_host_or_cohost(meeting_id, acting_user_id)
        return await self._participants.list_for_meeting(meeting_id)

    async def admit_participant(
        self, *, meeting_id: uuid.UUID, acting_user_id: uuid.UUID, participant_id: uuid.UUID
    ) -> MeetingParticipant:
        await self._require_host_or_cohost(meeting_id, acting_user_id)
        participant = await self._get_participant_in_meeting(meeting_id, participant_id)
        participant.admission_status = "admitted"
        return participant

    # ---- Phase 2: host / co-host controls --------------------------------

    async def remove_participant(
        self, *, meeting_id: uuid.UUID, acting_user_id: uuid.UUID, participant_id: uuid.UUID
    ) -> None:
        await self._require_host_or_cohost(meeting_id, acting_user_id)
        meeting = await self.get_meeting(meeting_id)
        participant = await self._get_participant_in_meeting(meeting_id, participant_id)
        if participant.role == "host":
            raise MeetingError("Cannot remove the host.")
        participant.admission_status = "removed"
        participant.left_at = datetime.now(UTC)
        await self._room_provider.remove_participant(
            room_name=meeting.livekit_room_name,
            participant_identity=participant.livekit_participant_identity,
        )

    async def promote_co_host(
        self, *, meeting_id: uuid.UUID, acting_user_id: uuid.UUID, participant_id: uuid.UUID
    ) -> MeetingParticipant:
        meeting = await self.get_meeting(meeting_id)
        if meeting.host_user_id != acting_user_id:
            raise MeetingError("Only the host can promote a co-host.")
        participant = await self._get_participant_in_meeting(meeting_id, participant_id)
        participant.role = "co_host"
        return participant

    async def set_participant_muted(
        self,
        *,
        meeting_id: uuid.UUID,
        acting_user_id: uuid.UUID,
        participant_id: uuid.UUID,
        muted: bool,
    ) -> None:
        await self._require_host_or_cohost(meeting_id, acting_user_id)
        meeting = await self.get_meeting(meeting_id)
        participant = await self._get_participant_in_meeting(meeting_id, participant_id)
        await self._room_provider.set_participant_can_publish(
            room_name=meeting.livekit_room_name,
            participant_identity=participant.livekit_participant_identity,
            can_publish=not muted,
        )

    async def set_locked(
        self, *, meeting_id: uuid.UUID, acting_user_id: uuid.UUID, locked: bool
    ) -> Meeting:
        meeting = await self.get_meeting(meeting_id)
        if meeting.host_user_id != acting_user_id:
            raise MeetingError("Only the host can lock or unlock this meeting.")
        meeting.locked_at = datetime.now(UTC) if locked else None
        return meeting

    async def set_waiting_room_enabled(
        self, *, meeting_id: uuid.UUID, acting_user_id: uuid.UUID, enabled: bool
    ) -> Meeting:
        """The host's choice between the two guest-entry experiences a
        non-host gets within their `prep_lead_minutes` early-join window
        (`_is_within_join_window`) — `enabled=True`: "hold to be
        admitted" (`join`/`guest_join` set a new participant's
        `admission_status` to `waiting`; they need `admit_participant`,
        or the scheduler's `auto_promote_waiting_conference_participants`
        auto-admits everyone the moment `scheduled_start_at` arrives, no
        host action required either way). `enabled=False`: "enter the
        room and wait there" — a new participant is `admitted`
        immediately and lands straight in the (possibly still-empty)
        room instead of a separate waiting state.

        Previously only settable once, at `create_meeting` time
        (`CreateMeetingRequest.waiting_room_enabled`) — this is the same
        setting, now changeable live during `prep`/`live` too, same
        "host-only, mirrors `set_locked`" restriction. Changing it only
        affects participants who join *after* the change; anyone already
        `waiting` or `admitted` keeps their current status."""
        meeting = await self.get_meeting(meeting_id)
        if meeting.host_user_id != acting_user_id:
            raise MeetingError("Only the host can change the waiting room setting.")
        meeting.waiting_room_enabled = enabled
        return meeting

    # ---- Phase 4: webinar/large-audience stage control ---------------------

    async def invite_to_stage(
        self, *, meeting_id: uuid.UUID, acting_user_id: uuid.UUID, participant_id: uuid.UUID
    ) -> MeetingParticipant:
        await self._require_host_or_cohost(meeting_id, acting_user_id)
        meeting = await self.get_meeting(meeting_id)
        participant = await self._get_participant_in_meeting(meeting_id, participant_id)
        participant.stage_status = "on_stage"
        await self._room_provider.set_participant_can_publish(
            room_name=meeting.livekit_room_name,
            participant_identity=participant.livekit_participant_identity,
            can_publish=True,
        )
        return participant

    async def move_to_audience(
        self, *, meeting_id: uuid.UUID, acting_user_id: uuid.UUID, participant_id: uuid.UUID
    ) -> MeetingParticipant:
        await self._require_host_or_cohost(meeting_id, acting_user_id)
        meeting = await self.get_meeting(meeting_id)
        participant = await self._get_participant_in_meeting(meeting_id, participant_id)
        if participant.role in _HOST_ROLES:
            raise MeetingError("Cannot move the host or a co-host to the audience.")
        participant.stage_status = "audience"
        await self._room_provider.set_participant_can_publish(
            room_name=meeting.livekit_room_name,
            participant_identity=participant.livekit_participant_identity,
            can_publish=False,
        )
        return participant

    # ---- Phase 4: webinar registration --------------------------------------

    async def register_for_meeting(
        self, *, meeting_id: uuid.UUID, email: str, display_name: str
    ) -> MeetingRegistration:
        """§35-style public flow, deliberately not auth-gated — RSVP-ing
        to a webinar shouldn't require a DITSALA account."""
        await self.get_meeting(meeting_id)  # 404s on an unknown meeting
        existing = await self._registrations.get_by_meeting_and_email(meeting_id, email)
        if existing is not None:
            existing.display_name = display_name
            return existing
        return await self._registrations.add(
            MeetingRegistration(meeting_id=meeting_id, email=email, display_name=display_name)
        )

    async def list_registrations(
        self, *, meeting_id: uuid.UUID, acting_user_id: uuid.UUID
    ) -> list[MeetingRegistration]:
        await self._require_host_or_cohost(meeting_id, acting_user_id)
        return await self._registrations.list_for_meeting(meeting_id)

    # ---- Phase 2: reactions / raise-hand (ephemeral, no DB row) ----------

    async def send_reaction(
        self, *, meeting_id: uuid.UUID, participant: MeetingParticipant, reaction: str
    ) -> None:
        meeting = await self.get_meeting(meeting_id)
        await self._broadcast_event(
            meeting, topic="reaction", participant_id=participant.id, extra={"reaction": reaction}
        )

    async def set_hand_raised(
        self, *, meeting_id: uuid.UUID, participant: MeetingParticipant, raised: bool
    ) -> None:
        meeting = await self.get_meeting(meeting_id)
        await self._broadcast_event(
            meeting, topic="hand_raise", participant_id=participant.id, extra={"raised": raised}
        )

    async def _broadcast_event(
        self, meeting: Meeting, *, topic: str, participant_id: uuid.UUID, extra: dict[str, Any]
    ) -> None:
        payload = json.dumps({"participant_id": str(participant_id), **extra}).encode()
        await self._room_provider.broadcast_data(
            room_name=meeting.livekit_room_name, payload=payload, topic=topic
        )

    # ---- Phase 2: recording ----------------------------------------------

    async def start_recording(
        self, *, meeting_id: uuid.UUID, acting_user_id: uuid.UUID
    ) -> MeetingRecording:
        await self._require_host_or_cohost(meeting_id, acting_user_id)
        meeting = await self.get_meeting(meeting_id)
        await self._require_tool(meeting, TOOL_RECORDING, "Recording")
        s3_key = f"meetings/{meeting_id}/recordings/{uuid.uuid4().hex}.mp4"
        handle = await self._room_provider.start_recording(
            room_name=meeting.livekit_room_name, s3_key=s3_key
        )
        return await self._recordings.add(
            MeetingRecording(
                meeting_id=meeting_id,
                egress_id=handle.egress_id,
                storage_key=s3_key,
                status=handle.status,
                started_at=datetime.now(UTC),
            )
        )

    async def stop_recording(
        self, *, meeting_id: uuid.UUID, acting_user_id: uuid.UUID, recording_id: uuid.UUID
    ) -> MeetingRecording:
        await self._require_host_or_cohost(meeting_id, acting_user_id)
        recording = await self._recordings.get(recording_id)
        if recording is None or recording.meeting_id != meeting_id:
            raise MeetingError("No such recording on this meeting.")
        handle: RecordingHandle = await self._room_provider.stop_recording(
            egress_id=recording.egress_id
        )
        recording.status = handle.status
        recording.duration_seconds = handle.duration_seconds
        recording.ended_at = datetime.now(UTC)
        return recording

    async def list_recordings(
        self, *, meeting_id: uuid.UUID, acting_user_id: uuid.UUID
    ) -> list[MeetingRecording]:
        await self._require_host_or_cohost(meeting_id, acting_user_id)
        return await self._recordings.list_for_meeting(meeting_id)

    # ---- Meeting documents — host/co-host share files, every participant
    # (including guests with no DITSALA account) can view them ------------

    async def request_document_upload(
        self,
        *,
        meeting_id: uuid.UUID,
        acting_user_id: uuid.UUID,
        filename: str,
        content_type: str,
        size_bytes: int,
    ) -> tuple[MeetingDocument, str]:
        uploader = await self._require_host_or_cohost(meeting_id, acting_user_id)
        if size_bytes > MAX_MEETING_DOCUMENT_SIZE_BYTES:
            raise MeetingError("File is too large.")
        key = f"meeting-documents/{meeting_id}/{uuid.uuid4()}"
        document = await self._documents.add(
            MeetingDocument(
                meeting_id=meeting_id,
                uploaded_by_participant_id=uploader.id,
                filename=filename,
                content_type=content_type,
                size_bytes=size_bytes,
                storage_key=key,
            )
        )
        upload_url = await self._storage.create_upload_url(key=key, content_type=content_type)
        return document, upload_url

    async def list_documents(
        self, *, meeting_id: uuid.UUID, participant_id: uuid.UUID
    ) -> list[MeetingDocument]:
        # Deliberately trusts a valid participant_id with no JWT — the same
        # trust model `get_participant_status` already uses (see its
        # docstring): a guest has no DITSALA account, so this is the only way
        # for them to see documents shared in a meeting they're actually in.
        await self._get_participant_in_meeting(meeting_id, participant_id)
        return await self._documents.list_for_meeting(meeting_id)

    async def get_document_download_url(
        self, *, meeting_id: uuid.UUID, participant_id: uuid.UUID, document_id: uuid.UUID
    ) -> str:
        await self._get_participant_in_meeting(meeting_id, participant_id)
        document = await self._documents.get(document_id)
        if document is None or document.meeting_id != meeting_id:
            raise MeetingError("No such document on this meeting.")
        return await self._storage.create_download_url(key=document.storage_key)

    async def delete_document(
        self, *, meeting_id: uuid.UUID, acting_user_id: uuid.UUID, document_id: uuid.UUID
    ) -> None:
        await self._require_host_or_cohost(meeting_id, acting_user_id)
        document = await self._documents.get(document_id)
        if document is None or document.meeting_id != meeting_id:
            raise MeetingError("No such document on this meeting.")
        # Removes the DB row only — StorageProvider has no delete method
        # today (same gap as messaging's MediaObject), so the underlying
        # object is orphaned in storage rather than actually deleted. A
        # disclosed scope cut, not a silent one — see docs/SECURITY_GAPS.md.
        await self._documents.delete(document)

    # ---- Phase 2: chat -----------------------------------------------------

    async def send_message(
        self,
        *,
        meeting_id: uuid.UUID,
        sender: MeetingParticipant,
        body: str,
        recipient_participant_id: uuid.UUID | None = None,
    ) -> MeetingMessage:
        if recipient_participant_id is not None:
            await self._get_participant_in_meeting(meeting_id, recipient_participant_id)
        message = await self._messages.add(
            MeetingMessage(
                meeting_id=meeting_id,
                sender_participant_id=sender.id,
                recipient_participant_id=recipient_participant_id,
                body=body,
            )
        )
        meeting = await self.get_meeting(meeting_id)
        await self._broadcast_event(
            meeting,
            topic="chat",
            participant_id=sender.id,
            extra={
                "message_id": str(message.id),
                "body": body,
                "recipient_participant_id": (
                    str(recipient_participant_id) if recipient_participant_id else None
                ),
            },
        )
        return message

    async def list_messages(
        self, *, meeting_id: uuid.UUID, participant_id: uuid.UUID
    ) -> list[MeetingMessage]:
        return await self._messages.list_for_participant(meeting_id, participant_id)

    # ---- multilingual chat (business-model kickoff §13/§18/§20) --------------
    #
    # Deliberately pull-based, not push-fan-out like VIP 1:1 chat's
    # `_push_to_recipient`: a conference can have dozens of participants
    # each wanting a different target language, so translating a message
    # into every language on every send would be wasted work for
    # languages nobody's reading right now. A participant asks for a
    # translation of a specific message into their own stored preference
    # when they need it — same shape the AI Interpreter already uses.
    #
    # Deliberately NOT gated behind `TranslationService.require_vip`, per
    # the business-model kickoff prompt's own FREE-tier feature list
    # ("Basic translation" is free; only AI *voice* interpretation and
    # premium conference features are paywalled) — unlike VIP Multilingual
    # Chat, which the VIP spec explicitly reserves for VIP-only 1:1
    # threads. A future per-plan entitlement check (`PlanService.
    # get_entitlement_for_user`) can replace this blanket allow once
    # conference plans have a real seat/membership model to resolve a
    # *meeting's* plan from — not guessed at here.
    #
    # Public given a valid participant_id, unlike `send_message`/
    # `list_messages` — same trust model as `list_documents`/
    # `get_participant_status` (guests have no JWT, and apps/meet's web
    # client itself has no authenticated-user flow yet, only guest-join
    # and the host-link handoff — see `[meetingId]/page.tsx`'s own
    # docstring). A guest's translation usage is attributed to the
    # meeting's host account (`_get_usage_attribution_user_id`) rather
    # than rejected, since `TranslationRequest.requested_by_user_id` is
    # NOT NULL and a guest has no user row of its own to charge.

    async def set_participant_language(
        self, *, meeting_id: uuid.UUID, participant_id: uuid.UUID, language: str
    ) -> ConferenceLanguagePreference:
        await self._get_participant_in_meeting(meeting_id, participant_id)
        return await self._conference_language_preferences.upsert(
            meeting_id=meeting_id, participant_id=participant_id, language=language
        )

    async def get_participant_language(
        self, participant_id: uuid.UUID
    ) -> ConferenceLanguagePreference | None:
        return await self._conference_language_preferences.get_by_participant(participant_id)

    async def list_participant_languages(
        self, meeting_id: uuid.UUID
    ) -> list[ConferenceLanguagePreference]:
        return await self._conference_language_preferences.list_for_meeting(meeting_id)

    async def translate_message(
        self, *, meeting_id: uuid.UUID, message_id: uuid.UUID, viewer_participant_id: uuid.UUID
    ) -> TranslationRequest:
        viewer = await self._get_participant_in_meeting(meeting_id, viewer_participant_id)
        message = await self._messages.get(message_id)
        if message is None or message.meeting_id != meeting_id:
            raise MeetingError("No such message.")
        viewer_language = await self.get_participant_language(viewer_participant_id)
        if viewer_language is None:
            raise MeetingError(
                "Set your conference language before requesting a translation."
            )
        if viewer.user_id is not None:
            requested_by_user_id = viewer.user_id
        else:
            meeting = await self.get_meeting(meeting_id)
            requested_by_user_id = meeting.host_user_id
        return await self._translation.translate_and_record(
            requested_by_user_id=requested_by_user_id,
            context_type="conference_caption",
            context_id=message.id,
            source_text=message.body,
            source_language=None,
            target_language=viewer_language.language,
        )

    # ---- Phase 2: polls ------------------------------------------------------

    async def create_poll(
        self,
        *,
        meeting_id: uuid.UUID,
        acting_user_id: uuid.UUID,
        creator: MeetingParticipant,
        question: str,
        options: list[str],
    ) -> MeetingPoll:
        await self._require_host_or_cohost(meeting_id, acting_user_id)
        if len(options) < 2:
            raise MeetingError("A poll needs at least two options.")
        poll = await self._polls.add(
            MeetingPoll(
                meeting_id=meeting_id,
                created_by_participant_id=creator.id,
                question=question,
                options=options,
            )
        )
        meeting = await self.get_meeting(meeting_id)
        await self._broadcast_event(
            meeting,
            topic="poll_created",
            participant_id=creator.id,
            extra={"poll_id": str(poll.id), "question": question, "options": options},
        )
        return poll

    async def vote_poll(
        self, *, poll_id: uuid.UUID, voter: MeetingParticipant, option_index: int
    ) -> None:
        poll = await self._polls.get(poll_id)
        if poll is None:
            raise MeetingError("No such poll.")
        if poll.closed_at is not None:
            raise MeetingError("This poll is closed.")
        if not 0 <= option_index < len(poll.options):
            raise MeetingError("Invalid poll option.")
        existing = await self._poll_votes.get_by_poll_and_voter(poll_id, voter.id)
        if existing is not None:
            existing.option_index = option_index
            return
        await self._poll_votes.add(
            MeetingPollVote(
                poll_id=poll_id, voter_participant_id=voter.id, option_index=option_index
            )
        )

    async def close_poll(
        self, *, meeting_id: uuid.UUID, acting_user_id: uuid.UUID, poll_id: uuid.UUID
    ) -> MeetingPoll:
        await self._require_host_or_cohost(meeting_id, acting_user_id)
        poll = await self._polls.get(poll_id)
        if poll is None or poll.meeting_id != meeting_id:
            raise MeetingError("No such poll on this meeting.")
        poll.closed_at = datetime.now(UTC)
        return poll

    async def get_poll_results(self, *, poll_id: uuid.UUID) -> PollResults:
        poll = await self._polls.get(poll_id)
        if poll is None:
            raise MeetingError("No such poll.")
        votes = await self._poll_votes.list_for_poll(poll_id)
        counts = {index: 0 for index in range(len(poll.options))}
        for vote in votes:
            counts[vote.option_index] = counts.get(vote.option_index, 0) + 1
        return PollResults(poll=poll, counts=counts)

    async def list_polls(self, *, meeting_id: uuid.UUID) -> list[MeetingPoll]:
        return await self._polls.list_for_meeting(meeting_id)

    # ---- Phase 2: Q&A ---------------------------------------------------------

    async def ask_question(
        self, *, meeting_id: uuid.UUID, asker: MeetingParticipant, body: str
    ) -> MeetingQuestion:
        question = await self._questions.add(
            MeetingQuestion(meeting_id=meeting_id, asked_by_participant_id=asker.id, body=body)
        )
        meeting = await self.get_meeting(meeting_id)
        await self._broadcast_event(
            meeting,
            topic="question_asked",
            participant_id=asker.id,
            extra={"question_id": str(question.id), "body": body},
        )
        return question

    async def upvote_question(self, *, question_id: uuid.UUID) -> MeetingQuestion:
        question = await self._questions.get(question_id)
        if question is None:
            raise MeetingError("No such question.")
        question.upvote_count += 1
        return question

    async def answer_question(
        self, *, meeting_id: uuid.UUID, acting_user_id: uuid.UUID, question_id: uuid.UUID
    ) -> MeetingQuestion:
        await self._require_host_or_cohost(meeting_id, acting_user_id)
        question = await self._get_question_in_meeting(meeting_id, question_id)
        question.status = "answered"
        question.answered_at = datetime.now(UTC)
        return question

    async def dismiss_question(
        self, *, meeting_id: uuid.UUID, acting_user_id: uuid.UUID, question_id: uuid.UUID
    ) -> MeetingQuestion:
        await self._require_host_or_cohost(meeting_id, acting_user_id)
        question = await self._get_question_in_meeting(meeting_id, question_id)
        question.status = "dismissed"
        return question

    async def list_questions(self, *, meeting_id: uuid.UUID) -> list[MeetingQuestion]:
        return await self._questions.list_for_meeting(meeting_id)

    async def _get_question_in_meeting(
        self, meeting_id: uuid.UUID, question_id: uuid.UUID
    ) -> MeetingQuestion:
        question = await self._questions.get(question_id)
        if question is None or question.meeting_id != meeting_id:
            raise MeetingError("No such question on this meeting.")
        return question

    # ---- Phase 2: breakout rooms ------------------------------------------

    async def create_breakout_rooms(
        self, *, meeting_id: uuid.UUID, acting_user_id: uuid.UUID, names: list[str]
    ) -> list[BreakoutRoom]:
        await self._require_host_or_cohost(meeting_id, acting_user_id)
        meeting = await self.get_meeting(meeting_id)
        await self._require_tool(meeting, TOOL_BREAKOUT_ROOMS, "Breakout rooms")
        if not names:
            raise MeetingError("At least one breakout room name is required.")
        rooms = []
        for name in names:
            rooms.append(
                await self._breakout_rooms.add(
                    BreakoutRoom(
                        meeting_id=meeting_id,
                        livekit_room_name=f"breakout-{uuid.uuid4().hex}",
                        name=name,
                    )
                )
            )
        return rooms

    async def list_breakout_rooms(self, *, meeting_id: uuid.UUID) -> list[BreakoutRoom]:
        return await self._breakout_rooms.list_for_meeting(meeting_id)

    async def assign_to_breakout_room(
        self,
        *,
        meeting_id: uuid.UUID,
        acting_user_id: uuid.UUID,
        breakout_room_id: uuid.UUID,
        participant_id: uuid.UUID,
    ) -> BreakoutRoomParticipant:
        await self._require_host_or_cohost(meeting_id, acting_user_id)
        breakout_room = await self._get_breakout_room_in_meeting(meeting_id, breakout_room_id)
        await self._get_participant_in_meeting(meeting_id, participant_id)
        existing = await self._breakout_room_participants.get_for_breakout_and_participant(
            breakout_room_id, participant_id
        )
        if existing is not None:
            return existing
        return await self._breakout_room_participants.add(
            BreakoutRoomParticipant(
                breakout_room_id=breakout_room.id, participant_id=participant_id
            )
        )

    async def join_breakout_room(
        self, *, meeting_id: uuid.UUID, breakout_room_id: uuid.UUID, participant: MeetingParticipant
    ) -> RoomAccessToken:
        breakout_room = await self._get_breakout_room_in_meeting(meeting_id, breakout_room_id)
        if breakout_room.closed_at is not None:
            raise MeetingError("This breakout room has closed.")
        assignment = await self._breakout_room_participants.get_for_breakout_and_participant(
            breakout_room_id, participant.id
        )
        if assignment is None:
            raise MeetingError("You have not been assigned to this breakout room.")
        return self._room_provider.create_access_token(
            room_name=breakout_room.livekit_room_name,
            participant_identity=participant.livekit_participant_identity,
            participant_name=(
                participant.guest_display_name or str(participant.user_id)
            ),
            is_host=False,
        )

    async def close_breakout_rooms(
        self, *, meeting_id: uuid.UUID, acting_user_id: uuid.UUID
    ) -> list[BreakoutRoom]:
        await self._require_host_or_cohost(meeting_id, acting_user_id)
        rooms = await self._breakout_rooms.list_for_meeting(meeting_id)
        now = datetime.now(UTC)
        for room in rooms:
            if room.closed_at is None:
                room.closed_at = now
        return rooms

    async def _get_breakout_room_in_meeting(
        self, meeting_id: uuid.UUID, breakout_room_id: uuid.UUID
    ) -> BreakoutRoom:
        room = await self._breakout_rooms.get(breakout_room_id)
        if room is None or room.meeting_id != meeting_id:
            raise MeetingError("No such breakout room on this meeting.")
        return room

    # ---- shared helpers ---------------------------------------------------

    async def assert_host_or_cohost(self, meeting_id: uuid.UUID, acting_user_id: uuid.UUID) -> None:
        """Public wrapper so router-level checks (e.g. `POST /host-link`,
        which needs to gate *before* doing anything else) can reuse this
        without reaching into a private method."""
        await self._require_host_or_cohost(meeting_id, acting_user_id)

    async def assert_participant_in_meeting(
        self, meeting_id: uuid.UUID, participant_id: uuid.UUID
    ) -> MeetingParticipant:
        """Same "public wrapper" reasoning as `assert_host_or_cohost` above,
        for the other trust model this codebase uses: router endpoints
        that are public given a valid participant_id (reactions/raise-hand/
        chat/polls/Q&A/breakout-room join — a guest has no JWT to prove
        membership any other way, same as `list_documents`'s existing
        pattern) need to validate that id belongs to this meeting before
        doing anything with it."""
        return await self._get_participant_in_meeting(meeting_id, participant_id)

    async def _require_host_or_cohost(
        self, meeting_id: uuid.UUID, acting_user_id: uuid.UUID
    ) -> MeetingParticipant:
        participant = await self._participants.get_by_meeting_and_user(
            meeting_id, acting_user_id
        )
        if participant is None or participant.role not in _HOST_ROLES:
            raise MeetingError("Only the host or a co-host can do this.")
        return participant

    async def _get_participant_in_meeting(
        self, meeting_id: uuid.UUID, participant_id: uuid.UUID
    ) -> MeetingParticipant:
        participant = await self._participants.get(participant_id)
        if participant is None or participant.meeting_id != meeting_id:
            raise MeetingError("No such participant on this meeting.")
        return participant
