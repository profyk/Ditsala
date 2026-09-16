import uuid
from datetime import datetime

from sqlalchemy import CursorResult, delete, func, select

from app.models.devices import AccountRecoveryRequest, Device, LoginAttempt, Session
from app.repositories.base import Repository


class DeviceRepository(Repository[Device]):
    model = Device

    async def list_for_user(self, user_id: uuid.UUID) -> list[Device]:
        result = await self.session.execute(self._select().where(Device.user_id == user_id))
        return list(result.scalars().all())

    async def count_created_since(self, since: datetime) -> int:
        """§28 Security Dashboard: 'device-churn outliers.' `created_at`
        (TimestampMixin) is naive — see UserRepository.count_created_since
        for why a tz-aware `since` needs stripping first."""
        result = await self.session.execute(
            select(func.count())
            .select_from(Device)
            .where(Device.created_at >= since.replace(tzinfo=None))
        )
        return result.scalar_one()


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

    async def count_active(self) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Session).where(Session.revoked_at.is_(None))
        )
        return result.scalar_one()


class LoginAttemptRepository(Repository[LoginAttempt]):
    model = LoginAttempt

    async def count_since(self, *, outcome: str | None = None, since: datetime) -> int:
        # created_at (TimestampMixin) is naive — see
        # UserRepository.count_created_since for why.
        stmt = (
            select(func.count())
            .select_from(LoginAttempt)
            .where(LoginAttempt.created_at >= since.replace(tzinfo=None))
        )
        if outcome is not None:
            stmt = stmt.where(LoginAttempt.outcome == outcome)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def list_recent_failures(
        self, *, since: datetime, limit: int = 100
    ) -> list[LoginAttempt]:
        result = await self.session.execute(
            self._select()
            .where(
                LoginAttempt.outcome == "failure",
                LoginAttempt.created_at >= since.replace(tzinfo=None),
            )
            .order_by(LoginAttempt.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def purge_older_than(self, cutoff: datetime) -> int:
        """§34.2: `login_attempts` retained 12 months, then hard-deleted."""
        result = await self.session.execute(
            delete(LoginAttempt).where(LoginAttempt.created_at < cutoff.replace(tzinfo=None))
        )
        assert isinstance(result, CursorResult)
        return result.rowcount


class AccountRecoveryRequestRepository(Repository[AccountRecoveryRequest]):
    model = AccountRecoveryRequest

    async def get_by_smile_id_job(self, smile_id_job_id: str) -> AccountRecoveryRequest | None:
        result = await self.session.execute(
            self._select().where(AccountRecoveryRequest.smile_id_job_id == smile_id_job_id)
        )
        return result.scalar_one_or_none()

    async def purge_older_than(self, cutoff: datetime) -> int:
        """§34.2: `account_recovery_requests` retained 12 months, then
        hard-deleted."""
        result = await self.session.execute(
            delete(AccountRecoveryRequest).where(
                AccountRecoveryRequest.created_at < cutoff.replace(tzinfo=None)
            )
        )
        assert isinstance(result, CursorResult)
        return result.rowcount
