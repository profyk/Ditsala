"""widen conversations.type for vip_multilingual

Revision ID: f8a4d2c6e1b3
Revises: e5c2b9a7f3d1
Create Date: 2026-09-22 06:00:00.000000

The original migration (631a559a0977) created this column as a
non-native SQLAlchemy Enum with no explicit `length=`, so it auto-sized
to VARCHAR(6) — the longest of the original two values, 'direct'.
Adding 'vip_multilingual' (16 chars) to the Python-side Enum in
app/models/messaging.py never widens the live column on its own (a
non-native Enum has no CHECK constraint to alter either, just a plain
VARCHAR) — this is the migration that was missing, caught by CI
actually exercising a real Postgres: every attempt to create a VIP
multilingual conversation was failing with
`StringDataRightTruncationError: value too long for type character
varying(6)`.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f8a4d2c6e1b3'
down_revision: str | Sequence[str] | None = 'e5c2b9a7f3d1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        'conversations', 'type',
        existing_type=sa.String(length=6),
        type_=sa.String(length=32),
        existing_nullable=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        'conversations', 'type',
        existing_type=sa.String(length=32),
        type_=sa.String(length=6),
        existing_nullable=False,
    )
