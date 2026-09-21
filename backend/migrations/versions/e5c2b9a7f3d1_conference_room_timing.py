"""conference room timing (prep lead + duration extensions)

Revision ID: e5c2b9a7f3d1
Revises: d3b8a1e4f7c9
Create Date: 2026-09-22 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e5c2b9a7f3d1'
down_revision: str | Sequence[str] | None = 'd3b8a1e4f7c9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'meetings',
        sa.Column('prep_lead_minutes', sa.Integer(), server_default=sa.text('15'), nullable=False),
    )
    op.add_column(
        'meetings',
        sa.Column(
            'duration_extended_minutes', sa.Integer(), server_default=sa.text('0'), nullable=False
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('meetings', 'duration_extended_minutes')
    op.drop_column('meetings', 'prep_lead_minutes')
