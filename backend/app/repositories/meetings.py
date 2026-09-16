import uuid

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
from app.repositories.base import Repository


class MeetingRepository(Repository[Meeting]):
    model = Meeting

    async def get_by_room_name(self, livekit_room_name: str) -> Meeting | None:
        result = await self.session.execute(
            self._select().where(Meeting.livekit_room_name == livekit_room_name)
        )
        return result.scalar_one_or_none()

    async def list_for_host(self, host_user_id: uuid.UUID) -> list[Meeting]:
        result = await self.session.execute(
            self._select()
            .where(Meeting.host_user_id == host_user_id)
            .order_by(Meeting.created_at.desc())
        )
        return list(result.scalars().all())


class MeetingParticipantRepository(Repository[MeetingParticipant]):
    model = MeetingParticipant

    async def get_by_meeting_and_user(
        self, meeting_id: uuid.UUID, user_id: uuid.UUID
    ) -> MeetingParticipant | None:
        result = await self.session.execute(
            self._select().where(
                MeetingParticipant.meeting_id == meeting_id,
                MeetingParticipant.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_meeting(self, meeting_id: uuid.UUID) -> list[MeetingParticipant]:
        result = await self.session.execute(
            self._select().where(MeetingParticipant.meeting_id == meeting_id)
        )
        return list(result.scalars().all())

    async def list_waiting(self, meeting_id: uuid.UUID) -> list[MeetingParticipant]:
        result = await self.session.execute(
            self._select().where(
                MeetingParticipant.meeting_id == meeting_id,
                MeetingParticipant.admission_status == "waiting",
            )
        )
        return list(result.scalars().all())


class MeetingRecordingRepository(Repository[MeetingRecording]):
    model = MeetingRecording

    async def get_by_egress_id(self, egress_id: str) -> MeetingRecording | None:
        result = await self.session.execute(
            self._select().where(MeetingRecording.egress_id == egress_id)
        )
        return result.scalar_one_or_none()

    async def list_for_meeting(self, meeting_id: uuid.UUID) -> list[MeetingRecording]:
        result = await self.session.execute(
            self._select()
            .where(MeetingRecording.meeting_id == meeting_id)
            .order_by(MeetingRecording.created_at.desc())
        )
        return list(result.scalars().all())


class MeetingMessageRepository(Repository[MeetingMessage]):
    model = MeetingMessage

    async def list_for_participant(
        self, meeting_id: uuid.UUID, participant_id: uuid.UUID
    ) -> list[MeetingMessage]:
        """Every broadcast message, plus any private message either sent or
        received by this participant — never another participant's private
        messages (§7 chat privacy)."""
        result = await self.session.execute(
            self._select()
            .where(
                MeetingMessage.meeting_id == meeting_id,
                (MeetingMessage.recipient_participant_id.is_(None))
                | (MeetingMessage.sender_participant_id == participant_id)
                | (MeetingMessage.recipient_participant_id == participant_id),
            )
            .order_by(MeetingMessage.created_at.asc())
        )
        return list(result.scalars().all())


class MeetingPollRepository(Repository[MeetingPoll]):
    model = MeetingPoll

    async def list_for_meeting(self, meeting_id: uuid.UUID) -> list[MeetingPoll]:
        result = await self.session.execute(
            self._select()
            .where(MeetingPoll.meeting_id == meeting_id)
            .order_by(MeetingPoll.created_at.asc())
        )
        return list(result.scalars().all())


class MeetingPollVoteRepository(Repository[MeetingPollVote]):
    model = MeetingPollVote

    async def get_by_poll_and_voter(
        self, poll_id: uuid.UUID, voter_participant_id: uuid.UUID
    ) -> MeetingPollVote | None:
        result = await self.session.execute(
            self._select().where(
                MeetingPollVote.poll_id == poll_id,
                MeetingPollVote.voter_participant_id == voter_participant_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_poll(self, poll_id: uuid.UUID) -> list[MeetingPollVote]:
        result = await self.session.execute(
            self._select().where(MeetingPollVote.poll_id == poll_id)
        )
        return list(result.scalars().all())


class MeetingQuestionRepository(Repository[MeetingQuestion]):
    model = MeetingQuestion

    async def list_for_meeting(self, meeting_id: uuid.UUID) -> list[MeetingQuestion]:
        result = await self.session.execute(
            self._select()
            .where(MeetingQuestion.meeting_id == meeting_id)
            .order_by(MeetingQuestion.upvote_count.desc(), MeetingQuestion.created_at.asc())
        )
        return list(result.scalars().all())


class BreakoutRoomRepository(Repository[BreakoutRoom]):
    model = BreakoutRoom

    async def list_for_meeting(self, meeting_id: uuid.UUID) -> list[BreakoutRoom]:
        result = await self.session.execute(
            self._select()
            .where(BreakoutRoom.meeting_id == meeting_id)
            .order_by(BreakoutRoom.created_at.asc())
        )
        return list(result.scalars().all())


class BreakoutRoomParticipantRepository(Repository[BreakoutRoomParticipant]):
    model = BreakoutRoomParticipant

    async def get_for_breakout_and_participant(
        self, breakout_room_id: uuid.UUID, participant_id: uuid.UUID
    ) -> BreakoutRoomParticipant | None:
        result = await self.session.execute(
            self._select().where(
                BreakoutRoomParticipant.breakout_room_id == breakout_room_id,
                BreakoutRoomParticipant.participant_id == participant_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_breakout(
        self, breakout_room_id: uuid.UUID
    ) -> list[BreakoutRoomParticipant]:
        result = await self.session.execute(
            self._select().where(BreakoutRoomParticipant.breakout_room_id == breakout_room_id)
        )
        return list(result.scalars().all())
