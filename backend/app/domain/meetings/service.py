"""
Ditsala Meet — docs/DITSALA_MEET_SPEC.md §4, §9. Phase 1 slice: create,
join (as the authenticated host/participant or as a guest), and end a
meeting. LiveKit (via `RoomProvider`) is the SFU; this service owns
meeting/participant state and never touches media itself.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.security import hash_secret, verify_secret
from app.domain.meetings.interfaces import RoomAccessToken, RoomProvider
from app.models.accounts import User
from app.models.meetings import Meeting, MeetingParticipant
from app.repositories.meetings import MeetingParticipantRepository, MeetingRepository

# §5: short-lived — long enough for one meeting sitting, not a durable
# credential. Kept distinct from LiveKit's own token TTL (services/meet/
# livekit.py) since this is Ditsala Meet's own domain-level constant.


class MeetingError(Exception):
    """Raised for meeting preconditions a caller should turn into a 4xx, not a 500."""


@dataclass(frozen=True)
class JoinResult:
    meeting: Meeting
    participant: MeetingParticipant
    access_token: RoomAccessToken


class MeetingService:
    def __init__(
        self,
        *,
        meetings: MeetingRepository,
        participants: MeetingParticipantRepository,
        room_provider: RoomProvider,
    ) -> None:
        self._meetings = meetings
        self._participants = participants
        self._room_provider = room_provider

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
    ) -> Meeting:
        meeting = await self._meetings.add(
            Meeting(
                host_user_id=host.id,
                livekit_room_name=f"meet-{uuid.uuid4().hex}",
                title=title,
                meeting_type=meeting_type,
                scheduled_start_at=scheduled_start_at,
                scheduled_duration_minutes=scheduled_duration_minutes,
                password_hash=hash_secret(password) if password else None,
                waiting_room_enabled=waiting_room_enabled,
            )
        )
        await self._participants.add(
            MeetingParticipant(
                meeting_id=meeting.id,
                user_id=host.id,
                role="host",
                livekit_participant_identity=str(host.id),
            )
        )
        return meeting

    async def get_meeting(self, meeting_id: uuid.UUID) -> Meeting:
        meeting = await self._meetings.get(meeting_id)
        if meeting is None:
            raise MeetingError("No such meeting.")
        return meeting

    async def join(
        self, *, meeting_id: uuid.UUID, user: User, password: str | None = None
    ) -> JoinResult:
        meeting = await self.get_meeting(meeting_id)
        self._check_joinable(meeting, password=password)

        participant = await self._participants.get_by_meeting_and_user(meeting_id, user.id)
        if participant is None:
            role = "host" if meeting.host_user_id == user.id else "participant"
            participant = await self._participants.add(
                MeetingParticipant(
                    meeting_id=meeting_id,
                    user_id=user.id,
                    role=role,
                    livekit_participant_identity=str(user.id),
                )
            )
        participant.joined_at = datetime.now(UTC)
        participant.left_at = None
        self._mark_live_if_needed(meeting)

        token = self._room_provider.create_access_token(
            room_name=meeting.livekit_room_name,
            participant_identity=participant.livekit_participant_identity,
            participant_name=user.display_name,
            is_host=participant.role in ("host", "co_host"),
        )
        return JoinResult(meeting=meeting, participant=participant, access_token=token)

    async def guest_join(
        self,
        *,
        meeting_id: uuid.UUID,
        guest_display_name: str,
        password: str | None = None,
    ) -> JoinResult:
        """§35 — no DITSALA account required or created; `user_id` stays
        null on the participant row, matching the model's own nullable
        design for exactly this case."""
        meeting = await self.get_meeting(meeting_id)
        self._check_joinable(meeting, password=password)

        guest_identity = f"guest-{uuid.uuid4().hex}"
        participant = await self._participants.add(
            MeetingParticipant(
                meeting_id=meeting_id,
                user_id=None,
                guest_display_name=guest_display_name,
                role="participant",
                livekit_participant_identity=guest_identity,
                joined_at=datetime.now(UTC),
            )
        )
        self._mark_live_if_needed(meeting)

        token = self._room_provider.create_access_token(
            room_name=meeting.livekit_room_name,
            participant_identity=guest_identity,
            participant_name=guest_display_name,
            is_host=False,
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

    def _check_joinable(self, meeting: Meeting, *, password: str | None) -> None:
        if meeting.status in ("ended", "cancelled"):
            raise MeetingError(f"Cannot join a meeting that has {meeting.status}.")
        if meeting.locked_at is not None:
            raise MeetingError("This meeting is locked.")
        if meeting.password_hash is not None:
            if password is None or not verify_secret(meeting.password_hash, password):
                raise MeetingError("Incorrect meeting password.")

    def _mark_live_if_needed(self, meeting: Meeting) -> None:
        if meeting.status == "scheduled":
            meeting.status = "live"
            meeting.actual_start_at = datetime.now(UTC)
