import uuid

from app.models.location import SosEvent, SosNotification
from app.repositories.base import Repository


class SosEventRepository(Repository[SosEvent]):
    model = SosEvent

    async def list_armed_for_user(self, user_id: uuid.UUID) -> list[SosEvent]:
        """Used by the cancellation-window check — see §26."""
        result = await self.session.execute(
            self._select().where(SosEvent.user_id == user_id, SosEvent.status == "armed")
        )
        return list(result.scalars().all())

    async def list_for_user(self, user_id: uuid.UUID) -> list[SosEvent]:
        """A user's own SOS history — §26: 'auditable and visible to the
        triggering user's own history'."""
        result = await self.session.execute(
            self._select().where(SosEvent.user_id == user_id)
        )
        return list(result.scalars().all())


class SosNotificationRepository(Repository[SosNotification]):
    model = SosNotification

    async def list_for_event(self, sos_event_id: uuid.UUID) -> list[SosNotification]:
        result = await self.session.execute(
            self._select().where(SosNotification.sos_event_id == sos_event_id)
        )
        return list(result.scalars().all())
