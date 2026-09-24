"""
VIP subscriptions — docs/adr/0012-normal-vip-tier-split.md. Payment
happens first (via Stitch), then the same KYC steps onboarding always
had (reusing `kyc_documents`/`kyc_face_verifications`, tagged
`purpose="vip_upgrade"`) — this table tracks that sequence for an
already-`active` user without touching `users.account_state`, which
stays `active` throughout.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

VIP_SUBSCRIPTION_STATUSES = (
    "pending_payment",
    "awaiting_kyc",
    "active",
    "cancelled",
    "expired",
    "failed",
)


class VipSubscription(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "vip_subscriptions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(
        Enum(
            *VIP_SUBSCRIPTION_STATUSES,
            name="vip_subscription_status",
            native_enum=False,
            validate_strings=True,
        ),
        default="pending_payment",
        server_default=text("'pending_payment'"),
    )
    payment_provider: Mapped[str] = mapped_column(
        String(32), default="stitch", server_default=text("'stitch'")
    )
    # Stitch's own payment/charge identifier — the join key its webhook
    # calls back with.
    external_payment_reference: Mapped[str] = mapped_column(String(128), unique=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


CONFERENCE_PLAN_PURCHASE_STATUSES = ("pending_payment", "paid", "failed")


class ConferencePlanPurchase(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Self-serve Conference Room plan upgrades via Stitch — same
    payment-first shape as `VipSubscription`, deliberately its own table
    rather than reusing that one: a conference-plan purchase needs no KYC
    step and is a one-off "set the plan" rather than a renewing
    subscription (`PlanService.set_user_conference_plan` is already a
    direct assignment, not period-tracked), and which of the four plan
    codes was actually purchased has to be recorded somewhere for the
    webhook to know what to grant."""

    __tablename__ = "conference_plan_purchases"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    plan_code: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        Enum(
            *CONFERENCE_PLAN_PURCHASE_STATUSES,
            name="conference_plan_purchase_status",
            native_enum=False,
            validate_strings=True,
        ),
        default="pending_payment",
        server_default=text("'pending_payment'"),
    )
    payment_provider: Mapped[str] = mapped_column(
        String(32), default="stitch", server_default=text("'stitch'")
    )
    external_payment_reference: Mapped[str] = mapped_column(String(128), unique=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


PLAN_PRODUCTS = ("free", "vip", "business", "conference")
PLAN_STATUSES = ("active", "archived")
BILLING_INTERVALS = ("month", "year", "one_time")


class Plan(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A sellable product line (§27-29 of the business-model kickoff prompt)
    — deliberately additive alongside `VipSubscription`/`VipUpgradeService`
    rather than replacing them: this table is the config-driven pricing/
    entitlement layer other domains ask "can this user do X," not a new
    subscription state machine. `code` is the stable string other code
    references (e.g. "vip", "conference_business"); `product` groups plans
    for admin-UI display and reporting, nothing more."""

    __tablename__ = "plans"

    code: Mapped[str] = mapped_column(String(64), unique=True)
    product: Mapped[str] = mapped_column(
        Enum(*PLAN_PRODUCTS, name="plan_product", native_enum=False)
    )
    name: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(
        Enum(*PLAN_STATUSES, name="plan_status", native_enum=False),
        default="active",
        server_default=text("'active'"),
    )


class PlanPrice(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One priced offering of a `Plan` — a plan can have several (monthly
    vs. annual, or several currencies) simultaneously `active`; admins
    archive an old price rather than mutate it in place so past invoices/
    audit-log entries still resolve to the price actually charged at the
    time (§29's "changes must be audited" — the row itself is the record,
    `admin.py`'s generic `audit_log` captures who changed what and why)."""

    __tablename__ = "plan_prices"

    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), index=True
    )
    currency: Mapped[str] = mapped_column(String(3))
    amount_cents: Mapped[int] = mapped_column(Integer)
    billing_interval: Mapped[str] = mapped_column(
        Enum(*BILLING_INTERVALS, name="billing_interval", native_enum=False)
    )
    status: Mapped[str] = mapped_column(
        Enum(*PLAN_STATUSES, name="plan_status", native_enum=False),
        default="active",
        server_default=text("'active'"),
    )
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Entitlement(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A generic key/value feature flag or usage limit attached to a
    `Plan` (§28's `conference.max_participants`, `translation.text`,
    `interpretation.minutes` examples) — deliberately schemaless so a new
    feature is an admin-configured row, not a new column/migration/
    deploy. `value` can be a bool, a number, or a small object depending
    on what `key` means; callers know the shape for the key they ask for."""

    __tablename__ = "entitlements"
    __table_args__ = (UniqueConstraint("plan_id", "key", name="uq_entitlements_plan_id_key"),)

    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(128))
    value: Mapped[Any] = mapped_column(JSONB)
