"""message_pin_and_forward

Revision ID: 11a7b72b68c1
Revises: a5eb01f16c72
Create Date: 2026-09-28 14:48:30.425698

Part of the chat rebuild's Phase 3 (see CLAUDE.md): per-message pin
(distinct from ConversationMember.pinned_at, which pins a whole
conversation) and a display-only is_forwarded flag — forwarding itself
is a client-side re-encrypt-per-conversation operation, never a server
copy, since one conversation's Sender Key can't decrypt another's
ciphertext.

Autogenerate also proposed dropping four unrelated indexes (plan_prices/
plans/translation_requests) — the same known metadata-comparison
cosmetic drift disclosed in CLAUDE.md, not touched here.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '11a7b72b68c1'
down_revision: str | Sequence[str] | None = 'a5eb01f16c72'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('messages', sa.Column('pinned_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        'messages',
        sa.Column('is_forwarded', sa.Boolean(), server_default='false', nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('messages', 'is_forwarded')
    op.drop_column('messages', 'pinned_at')
