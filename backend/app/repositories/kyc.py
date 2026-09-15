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
