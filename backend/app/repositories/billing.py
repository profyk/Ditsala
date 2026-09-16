import uuid

from app.models.billing import VipSubscription
from app.repositories.base import Repository


class VipSubscriptionRepository(Repository[VipSubscription]):
    model = VipSubscription

    async def get_by_external_reference(self, reference: str) -> VipSubscription | None:
        result = await self.session.execute(
            self._select().where(VipSubscription.external_payment_reference == reference)
        )
        return result.scalar_one_or_none()

    async def get_latest_for_user(self, user_id: uuid.UUID) -> VipSubscription | None:
        result = await self.session.execute(
            self._select()
            .where(VipSubscription.user_id == user_id)
            .order_by(VipSubscription.created_at.desc())
        )
        return result.scalars().first()
