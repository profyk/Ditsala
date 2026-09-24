"""remove hardcoded conference plan prices — admin sets every price, none seeded

Revision ID: b7d4e9f1a3c8
Revises: a1f5b8e3c2d7
Create Date: 2026-09-24 00:00:00.000000

Migration b4f7c1a9e6d2 seeded real ZAR/month prices (0, 14900, 39900,
149900 cents) for the four conference_* plans — genuine hardcoded
pricing, on explicit instruction now removed ("do not hardcode plan
pricings at all, admin will"). Matches the "no default price by
design" principle migration a1f5b8e3c2d7 already established for the
vip plan: the plans/entitlements (guest caps, duration, tools) stay
seeded — only the price is gone, so ConferencePlanUpgradeService now
correctly refuses every conference plan as "not configured yet" until
an admin sets a real one from the same /pricing page.

Deletes rather than archives: these prices were never actually charged
against (the self-serve upgrade flow they'd be used by didn't exist
until after this pass), so there's no real charge history that needs
to stay resolvable — unlike `set_price`'s own archive-on-change
behavior, which exists specifically to keep *past* charges resolvable.
Matched by exact plan code + the specific seeded amount, so a price an
admin has already set for real (a different amount) is left alone.
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d4e9f1a3c8"
down_revision: str | Sequence[str] | None = "a1f5b8e3c2d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEEDED_PRICES = [
    ("conference_free", 0),
    ("conference_pro", 14900),
    ("conference_premium", 39900),
    ("conference_enterprise", 149900),
]


def upgrade() -> None:
    bind = op.get_bind()
    for code, amount_cents in _SEEDED_PRICES:
        bind.execute(
            sa.text(
                """
                DELETE FROM plan_prices
                WHERE plan_id = (SELECT id FROM plans WHERE code = :code)
                  AND currency = 'ZAR'
                  AND billing_interval = 'month'
                  AND status = 'active'
                  AND amount_cents = :amount_cents
                """
            ),
            {"code": code, "amount_cents": amount_cents},
        )


def downgrade() -> None:
    """Re-seeds the original hardcoded prices — only for a clean
    rollback of this migration itself, not something to rely on as a
    real default."""
    bind = op.get_bind()
    for code, amount_cents in _SEEDED_PRICES:
        plan_id = bind.execute(
            sa.text("SELECT id FROM plans WHERE code = :code"), {"code": code}
        ).scalar_one_or_none()
        if plan_id is None:
            continue
        bind.execute(
            sa.text(
                """
                INSERT INTO plan_prices
                    (id, plan_id, currency, amount_cents, billing_interval, status,
                     effective_from, created_at, updated_at)
                SELECT :id, :plan_id, 'ZAR', :amount_cents, 'month', 'active',
                       now(), now(), now()
                WHERE NOT EXISTS (
                    SELECT 1 FROM plan_prices
                    WHERE plan_id = :plan_id AND currency = 'ZAR'
                      AND billing_interval = 'month' AND status = 'active'
                )
                """
            ),
            {"id": str(uuid.uuid4()), "plan_id": plan_id, "amount_cents": amount_cents},
        )
