import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field


class VipUpgradeStartRequest(BaseModel):
    """ADR 0014 — only meaningful for a normal-tier account that has
    none of these yet (a phone-only signup); ignored if the account
    already has an email."""

    email: EmailStr | None = None
    date_of_birth: date | None = None
    national_id: str | None = Field(default=None, min_length=4, max_length=64)


class VipUpgradeInitiationResponse(BaseModel):
    payment_url: str
    external_reference: str


class VipKycDocumentStartRequest(BaseModel):
    document_type: str = "sa_id"


class VipKycSdkTokenResponse(BaseModel):
    token: str
    job_id: str


class VipStatusResponse(BaseModel):
    """Backs the VIP dashboard's status card — null fields mean "never
    started an upgrade," not an error."""

    account_tier: str
    subscription_status: str | None
    current_period_end: datetime | None
    payment_provider: str | None


# --- admin plan/entitlement management (§27-29) ---


class CreatePlanRequest(BaseModel):
    code: str = Field(min_length=2, max_length=64)
    product: str = Field(pattern="^(free|vip|business|conference)$")
    name: str = Field(min_length=1, max_length=128)


class SetPlanStatusRequest(BaseModel):
    status: str = Field(pattern="^(active|archived)$")
    reason: str = Field(min_length=1, max_length=500)


class PlanResponse(BaseModel):
    id: uuid.UUID
    code: str
    product: str
    name: str
    status: str

    model_config = {"from_attributes": True}


class SetPlanPriceRequest(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    amount_cents: int = Field(ge=0)
    billing_interval: str = Field(pattern="^(month|year|one_time)$")
    reason: str = Field(min_length=1, max_length=500)


class PlanPriceResponse(BaseModel):
    id: uuid.UUID
    currency: str
    amount_cents: int
    billing_interval: str
    status: str
    effective_from: datetime
    effective_until: datetime | None

    model_config = {"from_attributes": True}


class SetEntitlementRequest(BaseModel):
    key: str = Field(min_length=1, max_length=128)
    value: Any
    reason: str = Field(min_length=1, max_length=500)


class EntitlementResponse(BaseModel):
    key: str
    value: Any

    model_config = {"from_attributes": True}


# --- public plan listing (Conference Room "plans & tools" screen) ---
# Read-only, any authenticated user — deliberately a narrower shape than
# the admin responses above: active plans/prices only, no archived
# history, no audit trail. See app/api/v1/routers/plans.py.


class PublicPlanResponse(BaseModel):
    id: uuid.UUID
    code: str
    product: str
    name: str
    prices: list[PlanPriceResponse]
    entitlements: list[EntitlementResponse]


class MyPlanResponse(BaseModel):
    plan_code: str


# --- Conference Room plan assignment (admin-only) ---------------------
# Separate axis from the messaging-app free/vip plan above — see
# `app/domain/billing/conference_plans.py` and
# `PlanService.resolve_conference_plan_code_for_user`.


class SetUserConferencePlanRequest(BaseModel):
    plan_code: str = Field(min_length=2, max_length=64)
    reason: str = Field(min_length=1, max_length=500)


class UserConferencePlanResponse(BaseModel):
    user_id: uuid.UUID
    conference_plan_code: str


class MyConferencePlanResponse(BaseModel):
    plan_code: str
