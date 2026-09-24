"""conference_plan_purchases

Revision ID: 08eac26506fb
Revises: d2e8f4a7c3b6
Create Date: 2026-09-24 08:44:33.159767

Self-serve Conference Room plan upgrades via Stitch. The autogenerate
pass that produced this file's first draft also proposed dropping
several unrelated, real tables (translation_requests, vip_messages,
plan_prices/plans indexes, etc.) — a SQLAlchemy metadata-import artifact
in this environment's alembic env, not an intended change. Hand-trimmed
to just the one real addition below.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '08eac26506fb'
down_revision: str | Sequence[str] | None = 'd2e8f4a7c3b6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('conference_plan_purchases',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('plan_code', sa.String(length=64), nullable=False),
    sa.Column('status', sa.Enum('pending_payment', 'paid', 'failed', name='conference_plan_purchase_status', native_enum=False), server_default=sa.text("'pending_payment'"), nullable=False),
    sa.Column('payment_provider', sa.String(length=32), server_default=sa.text("'stitch'"), nullable=False),
    sa.Column('external_payment_reference', sa.String(length=128), nullable=False),
    sa.Column('amount_cents', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=8), nullable=False),
    sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_conference_plan_purchases_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_conference_plan_purchases')),
    sa.UniqueConstraint('external_payment_reference', name=op.f('uq_conference_plan_purchases_external_payment_reference'))
    )
    op.create_index(op.f('ix_conference_plan_purchases_user_id'), 'conference_plan_purchases', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_conference_plan_purchases_user_id'), table_name='conference_plan_purchases')
    op.drop_table('conference_plan_purchases')
