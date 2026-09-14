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


class CallParticipantRepository(Repository[CallParticipant]):
    model = CallParticipant

    async def list_for_call(self, call_id: uuid.UUID) -> list[CallParticipant]:
        result = await self.session.execute(
            self._select().where(CallParticipant.call_id == call_id)
        )
        return list(result.scalars().all())
