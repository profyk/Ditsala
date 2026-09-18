import uuid
from datetime import datetime

from sqlalchemy import func, or_, select

from app.models.accounts import (
    DataSubjectRequest,
    EmailVerification,
    NextOfKin,
    PhoneVerification,
    User,
)
from app.repositories.base import Repository


class UserRepository(Repository[User]):
    model = User

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(self._select().where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_phone(self, phone: str) -> User | None:
        result = await self.session.execute(self._select().where(User.phone == phone))
        return result.scalar_one_or_none()

    async def list_by_phones(self, phones: list[str]) -> list[User]:
        """Bulk contact-matching lookup (§22 `phone_match` channel) — a
        single `WHERE phone IN (...)` rather than N calls to
        `get_by_phone`. Only `active` accounts match: a `pending_*` or
        `banned` row existing shouldn't be observable through this path."""
        if not phones:
            return []
        result = await self.session.execute(
            self._select().where(User.phone.in_(phones), User.account_state == "active")
        )
        return list(result.scalars().all())

    async def search(
        self,
        *,
        query: str | None = None,
        account_state: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[User]:
        """§28 Users: search by non-content metadata only (email, phone,
        display name, account state) — there is no message content to
        search server-side in the first place (§7.3)."""
        stmt = self._select()
        if query:
            like = f"%{query}%"
            stmt = stmt.where(
                or_(User.email.ilike(like), User.phone.ilike(like), User.display_name.ilike(like))
            )
        if account_state:
            stmt = stmt.where(User.account_state == account_state)
        stmt = stmt.order_by(User.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_state(self, account_state: str) -> list[User]:
        result = await self.session.execute(
            self._select().where(User.account_state == account_state)
        )
        return list(result.scalars().all())

    async def count_by_state(self, account_state: str) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(User).where(User.account_state == account_state)
        )
        return result.scalar_one()

    async def count_created_since(self, since: datetime) -> int:
        # users.created_at (TimestampMixin) is `timestamp without time zone`
        # — unlike purpose-built columns such as locked_until, it was never
        # declared DateTime(timezone=True), so a tz-aware `since` must be
        # stripped to compare cleanly (asyncpg rejects mixing the two).
        result = await self.session.execute(
            select(func.count())
            .select_from(User)
            .where(User.created_at >= since.replace(tzinfo=None))
        )
        return result.scalar_one()

    async def count_locked(self, *, now: datetime) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(User).where(User.locked_until > now)
        )
        return result.scalar_one()

    async def list_pending_hard_delete(self, *, now: datetime) -> list[User]:
        """§34.2 deletion cascade sweep — `hard_delete_after` is
        `DateTime(timezone=True)`, so no naive/aware mismatch here."""
        result = await self.session.execute(
            self._select().where(
                User.hard_delete_after.is_not(None), User.hard_delete_after <= now
            )
        )
        return list(result.scalars().all())


class NextOfKinRepository(Repository[NextOfKin]):
    model = NextOfKin

    async def list_for_user(self, user_id: uuid.UUID) -> list[NextOfKin]:
        result = await self.session.execute(
            select(NextOfKin).where(NextOfKin.user_id == user_id)
        )
        return list(result.scalars().all())


class EmailVerificationRepository(Repository[EmailVerification]):
    model = EmailVerification

    async def get_latest_pending(self, user_id: uuid.UUID) -> EmailVerification | None:
        result = await self.session.execute(
            self._select()
            .where(EmailVerification.user_id == user_id, EmailVerification.status == "pending")
            .order_by(EmailVerification.created_at.desc())
        )
        return result.scalars().first()


class PhoneVerificationRepository(Repository[PhoneVerification]):
    model = PhoneVerification

    async def get_latest_pending(self, user_id: uuid.UUID) -> PhoneVerification | None:
        result = await self.session.execute(
            self._select()
            .where(PhoneVerification.user_id == user_id, PhoneVerification.status == "pending")
            .order_by(PhoneVerification.created_at.desc())
        )
        return result.scalars().first()


class DataSubjectRequestRepository(Repository[DataSubjectRequest]):
    model = DataSubjectRequest

    async def list_for_user(self, user_id: uuid.UUID) -> list[DataSubjectRequest]:
        result = await self.session.execute(
            self._select()
            .where(DataSubjectRequest.user_id == user_id)
            .order_by(DataSubjectRequest.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_by_status(self, status: str) -> list[DataSubjectRequest]:
        result = await self.session.execute(
            self._select()
            .where(DataSubjectRequest.status == status)
            .order_by(DataSubjectRequest.due_at.asc())
        )
        return list(result.scalars().all())
