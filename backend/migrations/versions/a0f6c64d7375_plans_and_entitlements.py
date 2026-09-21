"""plans and entitlements

Revision ID: a0f6c64d7375
Revises: b7e3f1a9c2d4
Create Date: 2026-09-21 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a0f6c64d7375'
down_revision: str | Sequence[str] | None = 'b7e3f1a9c2d4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('plans',
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('product', sa.Enum('free', 'vip', 'business', 'conference', name='plan_product', native_enum=False), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('status', sa.Enum('active', 'archived', name='plan_status', native_enum=False), server_default=sa.text("'active'"), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_plans')),
    sa.UniqueConstraint('code', name=op.f('uq_plans_code'))
    )
    op.create_index(op.f('ix_plans_product'), 'plans', ['product'], unique=False)

    op.create_table('plan_prices',
    sa.Column('plan_id', sa.UUID(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('amount_cents', sa.Integer(), nullable=False),
    sa.Column('billing_interval', sa.Enum('month', 'year', 'one_time', name='billing_interval', native_enum=False), nullable=False),
    sa.Column('status', sa.Enum('active', 'archived', name='plan_status', native_enum=False), server_default=sa.text("'active'"), nullable=False),
    sa.Column('effective_from', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('effective_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['plan_id'], ['plans.id'], name=op.f('fk_plan_prices_plan_id_plans'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_plan_prices'))
    )
    op.create_index(op.f('ix_plan_prices_plan_id'), 'plan_prices', ['plan_id'], unique=False)
    op.create_index(
        'ix_plan_prices_plan_currency_interval_status',
        'plan_prices',
        ['plan_id', 'currency', 'billing_interval', 'status'],
        unique=False,
    )

    op.create_table('entitlements',
    sa.Column('plan_id', sa.UUID(), nullable=False),
    sa.Column('key', sa.String(length=128), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['plan_id'], ['plans.id'], name=op.f('fk_entitlements_plan_id_plans'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_entitlements')),
    sa.UniqueConstraint('plan_id', 'key', name=op.f('uq_entitlements_plan_id_key'))
    )
    op.create_index(op.f('ix_entitlements_plan_id'), 'entitlements', ['plan_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_entitlements_plan_id'), table_name='entitlements')
    op.drop_table('entitlements')

    op.drop_index('ix_plan_prices_plan_currency_interval_status', table_name='plan_prices')
    op.drop_index(op.f('ix_plan_prices_plan_id'), table_name='plan_prices')
    op.drop_table('plan_prices')

    op.drop_index(op.f('ix_plans_product'), table_name='plans')
    op.drop_table('plans')
