"""Admin revenue/subscriptions overview response shapes — see
`app/domain/admin/revenue.py` for what "estimated" means here."""

import uuid

from pydantic import BaseModel


class PlanRevenueLineResponse(BaseModel):
    plan_id: uuid.UUID
    plan_code: str
    plan_name: str
    product: str
    subscriber_count: int
    price_amount_cents: int | None
    price_currency: str | None
    estimated_monthly_cents: int

    model_config = {"from_attributes": True}


class RevenueOverviewResponse(BaseModel):
    lines: list[PlanRevenueLineResponse]
    total_estimated_monthly_cents: int
    total_subscribers: int

    model_config = {"from_attributes": True}
