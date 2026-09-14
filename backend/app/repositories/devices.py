import uuid

from app.models.devices import AccountRecoveryRequest, Device, LoginAttempt, Session
from app.repositories.base import Repository


class DeviceRepository(Repository[Device]):
    model = Device

    async def list_for_user(self, user_id: uuid.UUID) -> list[Device]:
        result = await self.session.execute(self._select().where(Device.user_id == user_id))
        return list(result.scalars().all())


class SessionRepository(Repository[Session]):
    model = Session

    async def get_by_refresh_token_hash(self, refresh_token_hash: str) -> Session | None:
        result = await self.session.execute(
            self._select().where(Session.refresh_token_hash == refresh_token_hash)
        )
        return result.scalar_one_or_none()


class LoginAttemptRepository(Repository[LoginAttempt]):
    model = LoginAttempt


class AccountRecoveryRequestRepository(Repository[AccountRecoveryRequest]):
    model = AccountRecoveryRequest
