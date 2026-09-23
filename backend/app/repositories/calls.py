import uuid

from app.models.calls import Call, CallParticipant
from app.repositories.base import Repository


class CallRepository(Repository[Call]):
    model = Call

    async def list_for_user(self, user_id: uuid.UUID) -> list[Call]:
        result = await self.session.execute(
            self._select()
            .join(CallParticipant, CallParticipant.call_id == Call.id)
            .where(CallParticipant.user_id == user_id)
        )
        return list(result.scalars().all())

    async def list_by_statuses(self, statuses: list[str], *, limit: int = 200) -> list[Call]:
        """Platform-wide, not scoped to either participant — backs the
        admin call-governance view, same "admin needs to see across every
        user" precedent `MeetingRepository.list_by_statuses` set."""
        result = await self.session.execute(
            self._select()
            .where(Call.status.in_(statuses))
            .order_by(Call.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


class CallParticipantRepository(Repository[CallParticipant]):
    model = CallParticipant

    async def list_for_call(self, call_id: uuid.UUID) -> list[CallParticipant]:
        result = await self.session.execute(
            self._select().where(CallParticipant.call_id == call_id)
        )
        return list(result.scalars().all())
