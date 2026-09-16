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
from datetime import UTC, datetime
from typing import Any

from app.core.security import hash_secret, verify_secret
from app.domain.meetings.interfaces import RecordingHandle, RoomAccessToken, RoomProvider
from app.models.accounts import User
from app.models.meetings import (
    BreakoutRoom,
    BreakoutRoomParticipant,
    Meeting,
    MeetingMessage,
    MeetingParticipant,
    MeetingPoll,
    MeetingPollVote,
    MeetingQuestion,
    MeetingRecording,
)
from app.repositories.meetings import (
    BreakoutRoomParticipantRepository,
    BreakoutRoomRepository,
    MeetingMessageRepository,
    MeetingParticipantRepository,
    MeetingPollRepository,
    MeetingPollVoteRepository,
    MeetingQuestionRepository,
    MeetingRecordingRepository,
    MeetingRepository,
)

_HOST_ROLES = ("host", "co_host")


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

    async def join(
        self, *, meeting_id: uuid.UUID, user: User, password: str | None = None
    ) -> JoinResult:
        meeting = await self.get_meeting(meeting_id)
        self._check_joinable(meeting, password=password)

        participant = await self._participants.get_by_meeting_and_user(meeting_id, user.id)
        if participant is None:
            role = "host" if meeting.host_user_id == user.id else "participant"
            needs_admission = meeting.waiting_room_enabled and role == "participant"
            participant = await self._participants.add(
                MeetingParticipant(
                    meeting_id=meeting_id,
                    user_id=user.id,
                    role=role,
                    livekit_participant_identity=str(user.id),
                    admission_status="waiting" if needs_admission else "admitted",
                )
            )
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
                joined_at=None if needs_admission else datetime.now(UTC),
            )
        )
        if needs_admission:
            return JoinResult(meeting=meeting, participant=participant, access_token=None)

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

    # ---- Phase 2: waiting room -------------------------------------------

    async def list_waiting_participants(
        self, *, meeting_id: uuid.UUID, acting_user_id: uuid.UUID
    ) -> list[MeetingParticipant]:
        await self._require_host_or_cohost(meeting_id, acting_user_id)
        return await self._participants.list_waiting(meeting_id)

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
