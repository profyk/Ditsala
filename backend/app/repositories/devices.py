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

    async def list_by_family(self, access_token_family_id: uuid.UUID) -> list[Session]:
        """Every rotation of the same underlying login — used for reuse
        detection: if a stale (already-rotated) refresh token is replayed,
        the whole family gets revoked (docs/DITSALA_MASTER_SPEC.md §16)."""
        result = await self.session.execute(
            self._select().where(Session.access_token_family_id == access_token_family_id)
        )
        return list(result.scalars().all())

    async def list_active_for_user(self, user_id: uuid.UUID) -> list[Session]:
        result = await self.session.execute(
            self._select().where(Session.user_id == user_id, Session.revoked_at.is_(None))
        )
        return list(result.scalars().all())


class LoginAttemptRepository(Repository[LoginAttempt]):
    model = LoginAttempt


class AccountRecoveryRequestRepository(Repository[AccountRecoveryRequest]):
    model = AccountRecoveryRequest
