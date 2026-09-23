"""
Revenue / subscriptions overview — a read-only aggregate over the
existing Plans/Entitlements data (`PlanService`) and current account-tier
headcounts. No new billing/ledger table: `VipSubscription` (Stitch) and
`PlanPrice` are already the real sources of truth for what's charged;
this is a fast, current-state snapshot for the admin dashboard, not a
replacement for real accounting. `estimated_monthly_cents` is exactly
that — an estimate from (active monthly price × current subscriber
count), not a reconciled ledger figure, and is labeled as such all the
way to the API response so nobody mistakes it for a real revenue report.
"""

import uuid
from dataclasses import dataclass

from app.domain.billing.plans import DEFAULT_FREE_PLAN_CODE, DEFAULT_VIP_PLAN_CODE, PlanService
from app.repositories.users import UserRepository

# users.account_tier's own values ("normal"/"vip") aren't the same strings
# as the messaging-axis plan codes ("free"/"vip") `PlanService.
# resolve_plan_code_for_user` maps them to — mirrored here rather than
# assuming they line up (they don't: "normal" != "free").
_ACCOUNT_TIER_TO_PLAN_CODE = {"normal": DEFAULT_FREE_PLAN_CODE, "vip": DEFAULT_VIP_PLAN_CODE}


@dataclass(frozen=True)
class PlanRevenueLine:
    plan_id: uuid.UUID
    plan_code: str
    plan_name: str
    product: str
    subscriber_count: int
    price_amount_cents: int | None
    price_currency: str | None
    estimated_monthly_cents: int


@dataclass(frozen=True)
class RevenueOverview:
    lines: list[PlanRevenueLine]
    total_estimated_monthly_cents: int
    total_subscribers: int


class RevenueService:
    def __init__(self, *, plans: PlanService, users: UserRepository) -> None:
        self._plans = plans
        self._users = users

    async def get_overview(self) -> RevenueOverview:
        # Two separate plan axes (see app/domain/billing/conference_plans.py's
        # module docstring) — merged here into one `plan_code -> count` map
        # since a plan code is unique across both.
        tier_counts = await self._users.count_grouped_by_account_tier()
        conference_counts = await self._users.count_grouped_by_conference_plan()
        subscriber_counts: dict[str, int] = {
            _ACCOUNT_TIER_TO_PLAN_CODE.get(tier, tier): count
            for tier, count in tier_counts.items()
        }
        subscriber_counts.update(conference_counts)

        lines: list[PlanRevenueLine] = []
        for plan in await self._plans.list_plans():
            if plan.status != "active":
                continue
            count = subscriber_counts.get(plan.code, 0)
            prices = [p for p in await self._plans.list_prices(plan.id) if p.status == "active"]
            monthly = next((p for p in prices if p.billing_interval == "month"), None)
            amount = monthly.amount_cents if monthly else None
            lines.append(
                PlanRevenueLine(
                    plan_id=plan.id,
                    plan_code=plan.code,
                    plan_name=plan.name,
                    product=plan.product,
                    subscriber_count=count,
                    price_amount_cents=amount,
                    price_currency=monthly.currency if monthly else None,
                    estimated_monthly_cents=(amount or 0) * count,
                )
            )

        return RevenueOverview(
            lines=lines,
            total_estimated_monthly_cents=sum(line.estimated_monthly_cents for line in lines),
            total_subscribers=sum(line.subscriber_count for line in lines),
        )
