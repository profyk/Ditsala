import uuid

from sqlalchemy import func, select

from app.models.accounts import KycDocument, KycFaceVerification
from app.repositories.base import Repository


class KycDocumentRepository(Repository[KycDocument]):
    model = KycDocument

    async def get_by_smile_id_job(self, smile_id_job_id: str) -> KycDocument | None:
        result = await self.session.execute(
            self._select().where(KycDocument.smile_id_job_id == smile_id_job_id)
        )
        return result.scalar_one_or_none()

    async def count_failed(self, user_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(KycDocument)
            .where(KycDocument.user_id == user_id, KycDocument.status == "failed")
        )
        return result.scalar_one()

    async def list_for_user(self, user_id: uuid.UUID) -> list[KycDocument]:
        result = await self.session.execute(
            self._select().where(KycDocument.user_id == user_id).order_by(KycDocument.created_at)
        )
        return list(result.scalars().all())

    async def get_latest_for_user_and_purpose(
        self, user_id: uuid.UUID, *, purpose: str
    ) -> KycDocument | None:
        """VipUpgradeService (docs/adr/0012) needs the most recent
        `vip_upgrade`-purposed document specifically — a user may also
        have `onboarding`-purposed rows that aren't relevant here."""
        result = await self.session.execute(
            self._select()
            .where(KycDocument.user_id == user_id, KycDocument.purpose == purpose)
            .order_by(KycDocument.created_at.desc())
        )
        return result.scalars().first()


class KycFaceVerificationRepository(Repository[KycFaceVerification]):
    model = KycFaceVerification

    async def get_by_smile_id_job(self, smile_id_job_id: str) -> KycFaceVerification | None:
        result = await self.session.execute(
            self._select().where(KycFaceVerification.smile_id_job_id == smile_id_job_id)
        )
        return result.scalar_one_or_none()

    async def count_failed(self, user_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(KycFaceVerification)
            .where(KycFaceVerification.user_id == user_id, KycFaceVerification.status == "failed")
        )
        return result.scalar_one()

    async def list_for_user(self, user_id: uuid.UUID) -> list[KycFaceVerification]:
        result = await self.session.execute(
            self._select()
            .where(KycFaceVerification.user_id == user_id)
            .order_by(KycFaceVerification.created_at)
        )
        return list(result.scalars().all())
