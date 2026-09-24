import uuid

from app.models.billing import ConferencePlanPurchase, Entitlement, Plan, PlanPrice, VipSubscription
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


class ConferencePlanPurchaseRepository(Repository[ConferencePlanPurchase]):
    model = ConferencePlanPurchase

    async def get_by_external_reference(self, reference: str) -> ConferencePlanPurchase | None:
        result = await self.session.execute(
            self._select().where(ConferencePlanPurchase.external_payment_reference == reference)
        )
        return result.scalar_one_or_none()

    async def get_latest_for_user(self, user_id: uuid.UUID) -> ConferencePlanPurchase | None:
        result = await self.session.execute(
            self._select()
            .where(ConferencePlanPurchase.user_id == user_id)
            .order_by(ConferencePlanPurchase.created_at.desc())
        )
        return result.scalars().first()


class PlanRepository(Repository[Plan]):
    model = Plan

    async def get_by_code(self, code: str) -> Plan | None:
        result = await self.session.execute(self._select().where(Plan.code == code))
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Plan]:
        result = await self.session.execute(self._select().order_by(Plan.created_at.asc()))
        return list(result.scalars().all())


class PlanPriceRepository(Repository[PlanPrice]):
    model = PlanPrice

    async def list_for_plan(self, plan_id: uuid.UUID) -> list[PlanPrice]:
        result = await self.session.execute(
            self._select()
            .where(PlanPrice.plan_id == plan_id)
            .order_by(PlanPrice.effective_from.desc())
        )
        return list(result.scalars().all())

    async def get_active_price(
        self, *, plan_id: uuid.UUID, currency: str, billing_interval: str
    ) -> PlanPrice | None:
        """The price a new purchase/upgrade should charge right now — the
        most recently effective `active` row for this plan/currency/
        interval combination. Archived prices are kept, never deleted, so
        past subscriptions/audit entries still resolve correctly."""
        result = await self.session.execute(
            self._select()
            .where(
                PlanPrice.plan_id == plan_id,
                PlanPrice.currency == currency,
                PlanPrice.billing_interval == billing_interval,
                PlanPrice.status == "active",
            )
            .order_by(PlanPrice.effective_from.desc())
        )
        return result.scalars().first()


class EntitlementRepository(Repository[Entitlement]):
    model = Entitlement

    async def list_for_plan(self, plan_id: uuid.UUID) -> list[Entitlement]:
        result = await self.session.execute(
            self._select().where(Entitlement.plan_id == plan_id)
        )
        return list(result.scalars().all())

    async def get_by_plan_and_key(self, plan_id: uuid.UUID, key: str) -> Entitlement | None:
        result = await self.session.execute(
            self._select().where(Entitlement.plan_id == plan_id, Entitlement.key == key)
        )
        return result.scalar_one_or_none()

    async def upsert(self, *, plan_id: uuid.UUID, key: str, value: object) -> Entitlement:
        existing = await self.get_by_plan_and_key(plan_id, key)
        if existing is not None:
            existing.value = value
            await self.session.flush()
            return existing
        return await self.add(Entitlement(plan_id=plan_id, key=key, value=value))
