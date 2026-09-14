import uuid

from app.models.push import PushToken
from app.repositories.base import Repository


class PushTokenRepository(Repository[PushToken]):
    model = PushToken

    async def list_active_for_device(self, device_id: uuid.UUID) -> list[PushToken]:
        result = await self.session.execute(
            self._select().where(PushToken.device_id == device_id, PushToken.active.is_(True))
        )
        return list(result.scalars().all())
