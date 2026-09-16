import uuid

from app.models.meetings import Meeting, MeetingParticipant
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
