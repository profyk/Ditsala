"""conversation_members_cleared_at

Revision ID: 5db914b49069
Revises: 11a7b72b68c1
Create Date: 2026-09-30 09:45:52.896152

Part of the chat rebuild's Phase 6 (see CLAUDE.md): "clear chat for me"
— a per-user history cursor, not a real delete. list_messages hides
anything created at or before this timestamp for the clearing member
only; everyone else's view of the conversation is untouched.

Autogenerate also proposed dropping four unrelated indexes (plan_prices/
plans/translation_requests) — the same known metadata-comparison
cosmetic drift disclosed in CLAUDE.md, not touched here.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '5db914b49069'
down_revision: str | Sequence[str] | None = '11a7b72b68c1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'conversation_members', sa.Column('cleared_at', sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('conversation_members', 'cleared_at')
