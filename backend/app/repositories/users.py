import uuid

from sqlalchemy import select

from app.models.accounts import EmailVerification, NextOfKin, PhoneVerification, User
from app.repositories.base import Repository


class UserRepository(Repository[User]):
    model = User

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(self._select().where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_phone(self, phone: str) -> User | None:
        result = await self.session.execute(self._select().where(User.phone == phone))
        return result.scalar_one_or_none()


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
