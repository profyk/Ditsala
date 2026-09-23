"""conference room plans: free/pro/premium/enterprise

Revision ID: b4f7c1a9e6d2
Revises: f8a4d2c6e1b3
Create Date: 2026-09-23 00:00:00.000000

Adds the Conference Room's own plan axis (separate from the messaging-app
free/vip split `PlanService.resolve_plan_code_for_user` already covers —
see that module's docstring and app/domain/billing/conference_plans.py):

- `users.conference_plan_code` — which of the four tiers a user's own
  hosted meetings resolve against. Defaults every existing user to
  `conference_free` (matches the free tier's entitlements seeded below,
  so nobody's existing meetings silently lose capability on upgrade).
- `meetings.max_participants` — the guest cap snapshotted from the
  host's plan at creation time (see that column's docstring in
  app/models/meetings.py for why it's snapshotted, not re-read live).
- Four `plans` rows (product="conference") with concrete entitlements —
  the actual "how many guests, how many hours" numbers an admin can see
  and edit from `apps/admin`'s Pricing / Conference Plans page from day
  one, rather than an empty table waiting for someone to type JSON by
  hand. Base ZAR list prices are seeded too (admin can override/add
  currencies via the existing `/admin/billing/plans/{id}/prices`
  endpoint) — Enterprise's is a starting list price, not a fixed rate;
  real enterprise deals go through a negotiated admin-set price the same
  way, not a separate mechanism.

Uses `op.get_bind()` (a plain SQLAlchemy `Connection`) rather than
`op.execute()` for every parameterized statement below — Alembic's own
`Operations.execute()` takes only a SQL string/Executable and an
`execution_options` kwarg, no bind-parameter dict, so passing user-
controlled-looking values (even fixed ones, like these plan codes)
through plain string formatting into `op.execute()` would be the wrong
habit to establish here regardless.
"""
import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4f7c1a9e6d2"
down_revision: str | Sequence[str] | None = "f8a4d2c6e1b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Plan code -> (display name, monthly ZAR cents, max_participants,
# max_duration_minutes, max_meetings_per_month, tool ids).
# None means "unlimited" for the numeric caps — mirrors how
# `Meeting.scheduled_duration_minutes`/`max_participants` already use
# `None` for "no cap" elsewhere in this schema.
_PLANS: list[tuple[str, str, int, int | None, int | None, int | None, list[str]]] = [
    (
        "conference_free",
        "Free",
        0,
        5,
        40,
        20,
        ["translation", "polls_qna"],
    ),
    (
        "conference_pro",
        "Pro",
        14900,
        25,
        180,
        None,
        ["translation", "polls_qna", "recording", "transcription"],
    ),
    (
        "conference_premium",
        "Premium",
        39900,
        100,
        480,
        None,
        [
            "translation",
            "polls_qna",
            "recording",
            "transcription",
            "ai_notes",
            "breakout_rooms",
            "webinar_registration",
            "analytics",
        ],
    ),
    (
        "conference_enterprise",
        "Enterprise",
        149900,
        None,
        None,
        None,
        [
            "translation",
            "polls_qna",
            "recording",
            "transcription",
            "ai_notes",
            "breakout_rooms",
            "webinar_registration",
            "analytics",
            "priority_support",
        ],
    ),
]


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "conference_plan_code",
            sa.String(length=64),
            server_default=sa.text("'conference_free'"),
            nullable=False,
        ),
    )
    op.add_column("meetings", sa.Column("max_participants", sa.Integer(), nullable=True))

    bind = op.get_bind()

    for code, name, price_cents, max_guests, max_minutes, max_meetings, tools in _PLANS:
        bind.execute(
            sa.text(
                """
                INSERT INTO plans (id, code, product, name, status, created_at, updated_at)
                VALUES (:id, :code, 'conference', :name, 'active', now(), now())
                ON CONFLICT (code) DO NOTHING
                """
            ),
            {"id": str(uuid.uuid4()), "code": code, "name": name},
        )
        # ON CONFLICT above means `id` might not be the row that actually
        # exists (a re-run after a partial failure) — resolve the real id
        # by code rather than assuming the just-generated one.
        plan_id = bind.execute(
            sa.text("SELECT id FROM plans WHERE code = :code"), {"code": code}
        ).scalar_one()

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
            {"id": str(uuid.uuid4()), "plan_id": plan_id, "amount_cents": price_cents},
        )

        entitlements = {
            "conference.max_participants": max_guests,
            "conference.max_duration_minutes": max_minutes,
            "conference.max_meetings_per_month": max_meetings,
            "conference.tools": tools,
        }
        for key, value in entitlements.items():
            bind.execute(
                sa.text(
                    """
                    INSERT INTO entitlements (id, plan_id, key, value, created_at, updated_at)
                    VALUES (:id, :plan_id, :key, CAST(:value AS jsonb), now(), now())
                    ON CONFLICT (plan_id, key) DO UPDATE SET value = EXCLUDED.value
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "plan_id": plan_id,
                    "key": key,
                    "value": json.dumps(value),
                },
            )


def downgrade() -> None:
    bind = op.get_bind()
    codes = [code for code, *_ in _PLANS]
    bind.execute(
        sa.text(
            "DELETE FROM entitlements WHERE plan_id IN "
            "(SELECT id FROM plans WHERE code = ANY(:codes))"
        ),
        {"codes": codes},
    )
    bind.execute(
        sa.text(
            "DELETE FROM plan_prices WHERE plan_id IN "
            "(SELECT id FROM plans WHERE code = ANY(:codes))"
        ),
        {"codes": codes},
    )
    bind.execute(sa.text("DELETE FROM plans WHERE code = ANY(:codes)"), {"codes": codes})
    op.drop_column("meetings", "max_participants")
    op.drop_column("users", "conference_plan_code")
