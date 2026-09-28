"""media_objects_uploaded_by_user_id

Revision ID: 750df89fef51
Revises: b7d4e9f1a3c8
Create Date: 2026-09-24 23:32:26.232402

Closes a real gap found while wiring up media messages: nothing ever
linked a MediaObject to the message that sends it (message_id stayed
null forever), and get_media_download_url's own membership check only
runs when message_id is set — so every uploaded object was silently
downloadable by any authenticated user who learned its id. This column
lets send_message verify the linking caller actually requested this
specific upload before attaching it (see MessagingService.send_message).

Autogenerate also proposed dropping four unrelated indexes (plan_prices/
plans/translation_requests) — the same known metadata-comparison
cosmetic drift disclosed in CLAUDE.md, not touched here.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '750df89fef51'
down_revision: str | Sequence[str] | None = 'b7d4e9f1a3c8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('media_objects', sa.Column('uploaded_by_user_id', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_media_objects_uploaded_by_user_id'), 'media_objects', ['uploaded_by_user_id'], unique=False)
    op.create_foreign_key(op.f('fk_media_objects_uploaded_by_user_id_users'), 'media_objects', 'users', ['uploaded_by_user_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f('fk_media_objects_uploaded_by_user_id_users'), 'media_objects', type_='foreignkey')
    op.drop_index(op.f('ix_media_objects_uploaded_by_user_id'), table_name='media_objects')
    op.drop_column('media_objects', 'uploaded_by_user_id')
