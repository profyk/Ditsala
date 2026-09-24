"""
Ditsala plans/entitlements — the config-driven pricing layer the business-
model kickoff prompt asks for (§27-29: "do not hard-code prices," "can this
user use recording," "how many interpretation minutes remain"). Additive
alongside `VipUpgradeService`/`VipSubscription`: this module does not
replace the real, live Stitch payment flow — it's the layer other domains
ask "what does this user's plan allow," resolved today from the existing
`users.account_tier` (vip|normal), with Business/Conference plan
resolution (an org/seat membership, not yet modeled) a documented next
step rather than guessed at here.

Every plan/price/entitlement mutation is audit-logged via the existing
generic `audit_log` (`AuditLogRepository`) — no separate `pricing_audit_log`
table, since that would duplicate a real system this codebase already has
(see CLAUDE.md's "do not duplicate existing... database... systems").
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from app.models.accounts import User
from app.models.admin import AuditLog
from app.models.billing import Entitlement, Plan, PlanPrice
from app.repositories.admin import AuditLogRepository
from app.repositories.billing import EntitlementRepository, PlanPriceRepository, PlanRepository
from app.repositories.users import UserRepository

# The MVP user -> plan resolution: every real account today is either
# `normal` (free) or `vip`. Business/Conference plans need an org/seat
# model that doesn't exist yet — resolving those is this module's next
# real extension point, not something to fake here.
DEFAULT_FREE_PLAN_CODE = "free"
DEFAULT_VIP_PLAN_CODE = "vip"

# The Conference Room axis is separate from the messaging-app free/vip
# axis above — a `normal` messaging user can still be on a paid
# Conference plan (or vice versa). Resolved from `users.conference_plan_code`
# (migration <conference plans>) rather than derived from `account_tier`,
# since there's no org/seat model to derive it from yet — see
# `resolve_conference_plan_code_for_user`. The seed data for these four
# codes/entitlements lives in that same migration and is mirrored (for
# app-layer defaults only, not re-run as code) in
# `app/domain/billing/conference_plans.py`.
DEFAULT_CONFERENCE_PLAN_CODE = "conference_free"


class PlanError(Exception):
    """Raised for plan/pricing preconditions a caller should turn into a 4xx, not a 500."""


class PlanService:
    def __init__(
        self,
        *,
        plans: PlanRepository,
        plan_prices: PlanPriceRepository,
        entitlements: EntitlementRepository,
        audit_log: AuditLogRepository,
        # Optional — only needed for `set_user_conference_plan` (an admin
        # action). Every existing caller/test constructs this service
        # without it, so it stays optional rather than forcing every call
        # site to thread a UserRepository through for a feature it doesn't use.
        users: UserRepository | None = None,
    ) -> None:
        self._plans = plans
        self._plan_prices = plan_prices
        self._entitlements = entitlements
        self._audit_log = audit_log
        self._users = users

    async def _log(
        self,
        admin_id: uuid.UUID,
        action: str,
        *,
        target_id: uuid.UUID | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> None:
        await self._audit_log.add(
            AuditLog(
                created_at=datetime.now(UTC),
                actor_type="admin",
                actor_id=admin_id,
                action=action,
                target_type="plan",
                target_id=target_id,
                metadata_json=metadata_json,
            )
        )

    # --- plans ---

    async def list_plans(self) -> list[Plan]:
        return await self._plans.list_all()

    async def get_plan_by_code(self, code: str) -> Plan | None:
        return await self._plans.get_by_code(code)

    async def create_plan(
        self, *, admin_id: uuid.UUID, code: str, product: str, name: str
    ) -> Plan:
        if await self._plans.get_by_code(code) is not None:
            raise PlanError(f"A plan with code {code!r} already exists.")
        plan = await self._plans.add(Plan(code=code, product=product, name=name))
        await self._log(
            admin_id, "admin.plan.created", target_id=plan.id,
            metadata_json={"code": code, "product": product, "name": name},
        )
        return plan

    async def set_plan_status(
        self, *, admin_id: uuid.UUID, plan_id: uuid.UUID, status: str, reason: str
    ) -> Plan:
        plan = await self._plans.get(plan_id)
        if plan is None:
            raise PlanError("No such plan.")
        before = plan.status
        plan.status = status
        await self._log(
            admin_id, "admin.plan.status_changed", target_id=plan.id,
            metadata_json={"before": before, "after": status, "reason": reason},
        )
        return plan

    # --- prices ---

    async def list_prices(self, plan_id: uuid.UUID) -> list[PlanPrice]:
        return await self._plan_prices.list_for_plan(plan_id)

    async def get_active_price(
        self, *, plan_code: str, currency: str, billing_interval: str
    ) -> PlanPrice | None:
        plan = await self._plans.get_by_code(plan_code)
        if plan is None:
            return None
        return await self._plan_prices.get_active_price(
            plan_id=plan.id, currency=currency, billing_interval=billing_interval
        )

    async def set_price(
        self,
        *,
        admin_id: uuid.UUID,
        plan_id: uuid.UUID,
        currency: str,
        amount_cents: int,
        billing_interval: str,
        reason: str,
    ) -> PlanPrice:
        """Archives any existing `active` price for this plan/currency/
        interval and creates a new one, rather than mutating a price in
        place — past subscriptions and audit-log entries stay resolvable
        against the price that was actually active when they were charged."""
        plan = await self._plans.get(plan_id)
        if plan is None:
            raise PlanError("No such plan.")

        existing = await self._plan_prices.get_active_price(
            plan_id=plan_id, currency=currency, billing_interval=billing_interval
        )
        before = (
            {"amount_cents": existing.amount_cents, "currency": existing.currency}
            if existing is not None
            else None
        )
        if existing is not None:
            existing.status = "archived"
            existing.effective_until = datetime.now(UTC)

        new_price = await self._plan_prices.add(
            PlanPrice(
                plan_id=plan_id,
                currency=currency,
                amount_cents=amount_cents,
                billing_interval=billing_interval,
            )
        )
        await self._log(
            admin_id, "admin.plan.price_changed", target_id=plan_id,
            metadata_json={
                "before": before,
                "after": {"amount_cents": amount_cents, "currency": currency},
                "billing_interval": billing_interval,
                "reason": reason,
            },
        )
        return new_price

    # --- entitlements ---

    async def list_entitlements(self, plan_id: uuid.UUID) -> list[Entitlement]:
        return await self._entitlements.list_for_plan(plan_id)

    async def set_entitlement(
        self, *, admin_id: uuid.UUID, plan_id: uuid.UUID, key: str, value: object, reason: str
    ) -> Entitlement:
        plan = await self._plans.get(plan_id)
        if plan is None:
            raise PlanError("No such plan.")
        before = await self._entitlements.get_by_plan_and_key(plan_id, key)
        # Captured as a plain value, not a reference to `before` itself —
        # `upsert` below fetches and mutates the *same* identity-mapped
        # ORM object in place (same session, same primary key), so
        # `before.value` read after the upsert would already reflect the
        # new value, not the old one (caught by CI running against a real
        # Postgres/session, where the identity map is actually exercised).
        before_value = before.value if before is not None else None
        entitlement = await self._entitlements.upsert(plan_id=plan_id, key=key, value=value)
        await self._log(
            admin_id, "admin.plan.entitlement_changed", target_id=plan_id,
            metadata_json={
                "key": key,
                "before": before_value,
                "after": value,
                "reason": reason,
            },
        )
        return entitlement

    # --- resolution: what other domains actually call ---

    def resolve_plan_code_for_user(self, user: User) -> str:
        """MVP mapping only — see module docstring. Business/Conference
        plan resolution is a real, documented gap until org membership
        exists, not silently approximated here."""
        return DEFAULT_VIP_PLAN_CODE if user.account_tier == "vip" else DEFAULT_FREE_PLAN_CODE

    def resolve_conference_plan_code_for_user(self, user: User) -> str:
        """The Conference Room's own plan axis — see module docstring.
        `users.conference_plan_code` is set by an admin action
        (`set_user_conference_plan`) since there's no self-serve payment
        flow for these four tiers yet (same "admin sets it, no default
        price by design" precedent VIP pricing already established via
        `system_config`)."""
        return user.conference_plan_code or DEFAULT_CONFERENCE_PLAN_CODE

    async def get_entitlement_by_plan_code(
        self, plan_code: str, key: str, *, default: Any = None
    ) -> Any:
        """The shared lookup both `get_entitlement_for_user` and any
        conference-plan caller (`app/domain/meetings/entitlements.py`)
        go through — one place that turns "plan code + key" into a
        resolved value, so the two plan axes above don't each grow their
        own copy of this."""
        plan = await self._plans.get_by_code(plan_code)
        if plan is None:
            return default
        entitlement = await self._entitlements.get_by_plan_and_key(plan.id, key)
        return entitlement.value if entitlement is not None else default

    async def get_entitlement_for_user(
        self, user: User, key: str, *, default: Any = None
    ) -> Any:
        plan_code = self.resolve_plan_code_for_user(user)
        return await self.get_entitlement_by_plan_code(plan_code, key, default=default)

    async def set_user_conference_plan(
        self, *, admin_id: uuid.UUID, user_id: uuid.UUID, plan_code: str, reason: str
    ) -> User:
        """Admin-only (§27-29 style audit-logged mutation, mirrors every
        other setter in this class). Refuses a `plan_code` that isn't a
        real, active `product="conference"` plan — an admin fat-fingering
        a typo here would otherwise silently downgrade a paying user to
        the unlimited-fallback `DEFAULT_ENTITLEMENTS` every conference
        entitlement lookup uses when a plan can't be found."""
        if self._users is None:
            raise PlanError("PlanService was constructed without a UserRepository.")
        user = await self._users.get(user_id)
        if user is None:
            raise PlanError("No such user.")
        plan = await self._plans.get_by_code(plan_code)
        if plan is None or plan.product != "conference" or plan.status != "active":
            raise PlanError(f"{plan_code!r} is not an active conference plan.")
        before = user.conference_plan_code
        user.conference_plan_code = plan_code
        await self._log(
            admin_id,
            "admin.user.conference_plan_changed",
            target_id=user_id,
            metadata_json={"before": before, "after": plan_code, "reason": reason},
        )
        return user

    async def apply_paid_conference_plan(self, *, user_id: uuid.UUID, plan_code: str) -> User:
        """System-actor counterpart to `set_user_conference_plan` above —
        called by `ConferencePlanUpgradeService.handle_payment_webhook`
        once Stitch confirms payment, not by an admin, so this logs with
        `actor_type="system"` rather than `_log`'s hardcoded "admin" and
        needs no `reason`/`admin_id`. Same validation as the admin path:
        refuses a `plan_code` that isn't a real, active `product=
        "conference"` plan."""
        if self._users is None:
            raise PlanError("PlanService was constructed without a UserRepository.")
        user = await self._users.get(user_id)
        if user is None:
            raise PlanError("No such user.")
        plan = await self._plans.get_by_code(plan_code)
        if plan is None or plan.product != "conference" or plan.status != "active":
            raise PlanError(f"{plan_code!r} is not an active conference plan.")
        before = user.conference_plan_code
        user.conference_plan_code = plan_code
        await self._audit_log.add(
            AuditLog(
                created_at=datetime.now(UTC),
                actor_type="system",
                actor_id=user_id,
                action="user.conference_plan_upgraded",
                target_type="plan",
                target_id=user_id,
                metadata_json={"before": before, "after": plan_code},
            )
        )
        return user
