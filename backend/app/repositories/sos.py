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


class SosNotificationRepository(Repository[SosNotification]):
    model = SosNotification
