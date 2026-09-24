"""
Self-serve Conference Room plan upgrade via Stitch (explicit user ask:
"add an upgrade my plans button... wire it end to end"). Same payment-
first shape as `VipUpgradeService`, deliberately simpler: no KYC step
(Conference plans aren't identity-gated the way VIP is) and no renewal-
period tracking (`PlanService.apply_paid_conference_plan` is a direct
assignment, matching the admin path's own "no subscription semantics"
design) — just "pay for this plan code, then have it."
"""

import uuid
from datetime import UTC, datetime

from app.domain.billing.conference_plans import CONFERENCE_PLAN_CODES
from app.domain.billing.interfaces import PaymentInitiation, PaymentProvider, PaymentWebhookResult
from app.domain.billing.plans import PlanError, PlanService
from app.models.accounts import User
from app.models.billing import ConferencePlanPurchase
from app.repositories.billing import ConferencePlanPurchaseRepository

CONFERENCE_UPGRADE_CURRENCY = "ZAR"
CONFERENCE_UPGRADE_BILLING_INTERVAL = "month"


class ConferencePlanUpgradeError(Exception):
    """Raised for upgrade preconditions a caller should turn into a 4xx, not a 500."""


class ConferencePlanUpgradeService:
    def __init__(
        self,
        *,
        purchases: ConferencePlanPurchaseRepository,
        plans: PlanService,
        payment_provider: PaymentProvider,
    ) -> None:
        self._purchases = purchases
        self._plans = plans
        self._payment_provider = payment_provider

    async def start_upgrade(self, user: User, *, plan_code: str) -> PaymentInitiation | None:
        """`None` means the target plan was free and got applied
        immediately — no payment needed, so there's nothing to redirect
        the client to. Anything else returns where to send them to pay."""
        if plan_code not in CONFERENCE_PLAN_CODES:
            raise ConferencePlanUpgradeError(f"{plan_code!r} is not a Conference Room plan.")
        if user.conference_plan_code == plan_code:
            raise ConferencePlanUpgradeError("You're already on this plan.")

        price = await self._plans.get_active_price(
            plan_code=plan_code,
            currency=CONFERENCE_UPGRADE_CURRENCY,
            billing_interval=CONFERENCE_UPGRADE_BILLING_INTERVAL,
        )
        if price is None:
            raise ConferencePlanUpgradeError(
                f"{plan_code!r} has no active price configured yet — an admin must set one first."
            )

        if price.amount_cents == 0:
            try:
                await self._plans.apply_paid_conference_plan(user_id=user.id, plan_code=plan_code)
            except PlanError as exc:
                raise ConferencePlanUpgradeError(str(exc)) from exc
            return None

        pending = await self._purchases.get_latest_for_user(user.id)
        if pending is not None and pending.status == "pending_payment":
            raise ConferencePlanUpgradeError(
                "A Conference Room plan upgrade is already in progress for this account."
            )

        initiation = await self._payment_provider.initiate_payment(
            user_id=user.id,
            amount_cents=price.amount_cents,
            currency=price.currency,
            description=f"DITSALA Conference Room upgrade ({plan_code})",
        )
        await self._purchases.add(
            ConferencePlanPurchase(
                user_id=user.id,
                plan_code=plan_code,
                external_payment_reference=initiation.external_reference,
                amount_cents=price.amount_cents,
                currency=price.currency,
            )
        )
        return initiation

    async def handle_payment_webhook(
        self, result: PaymentWebhookResult
    ) -> ConferencePlanPurchase:
        purchase = await self._purchases.get_by_external_reference(result.external_reference)
        if purchase is None:
            raise ConferencePlanUpgradeError("Unknown payment reference.")
        if result.status == "paid":
            purchase.status = "paid"
            purchase.paid_at = datetime.now(UTC)
            try:
                await self._plans.apply_paid_conference_plan(
                    user_id=purchase.user_id, plan_code=purchase.plan_code
                )
            except PlanError as exc:
                raise ConferencePlanUpgradeError(str(exc)) from exc
        else:
            purchase.status = "failed"
        return purchase

    async def get_latest_purchase(self, user_id: uuid.UUID) -> ConferencePlanPurchase | None:
        """Backs a status check so the client can poll after redirecting
        back from Stitch's hosted payment page, the same way VIP's own
        status endpoint does."""
        return await self._purchases.get_latest_for_user(user_id)
