"""seed vip plan row (unify VIP pricing onto the real plans/plan_prices pipeline)

Revision ID: a1f5b8e3c2d7
Revises: 08eac26506fb
Create Date: 2026-09-24 00:00:00.000000

VIP pricing previously lived in a raw system_config key ("vip_pricing",
a JSON blob with no admin UI purpose-built for it, no price history/
versioning, and disconnected from the real plans/plan_prices/
entitlements system Conference plans already use correctly) — a real,
confusing inconsistency, found and fixed on explicit instruction
("make sure admin panel has the correct pipelines for pricing for both
vip and conference plans... do not hardcode prices").

This seeds only the *plan* row (code="vip", product="vip") — no price.
An admin must still set one via the same /pricing page Conference plans
already use, same "no default price by design" safety principle the
old system_config mechanism already had, just through the correct
mechanism now.
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1f5b8e3c2d7"
down_revision: str | Sequence[str] | None = "08eac26506fb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO plans (id, code, product, name, status, created_at, updated_at)
            VALUES (:id, 'vip', 'vip', 'VIP', 'active', now(), now())
            ON CONFLICT (code) DO NOTHING
            """
        ),
        {"id": str(uuid.uuid4())},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM plans WHERE code = 'vip'"))
