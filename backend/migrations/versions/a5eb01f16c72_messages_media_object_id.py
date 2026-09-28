"""messages_media_object_id

Revision ID: a5eb01f16c72
Revises: 750df89fef51
Create Date: 2026-09-28 10:51:39.124543

Real gap this closes: 750df89fef51 linked a MediaObject to the message
that sends it (MediaObject.message_id), but MessageResponse had no way
to tell a *recipient* which MediaObject a media/voice_note message
points to — the only link was that one direction. This adds the
reverse pointer directly on Message, set once at send_message time
alongside the other side, so list_messages can expose it for free.

The two tables now have a genuine circular FK (MediaObject.message_id
-> messages.id, Message.media_object_id -> media_objects.id) — the new
one is declared `use_alter=True` (see app/models/messaging.py) so
SQLAlchemy defers it to its own ALTER TABLE instead of raising an
unresolvable-cycle warning when sorting table creation order.

Autogenerate also proposed dropping four unrelated indexes (plan_prices/
plans/translation_requests) — the same known metadata-comparison
cosmetic drift disclosed in CLAUDE.md, not touched here.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a5eb01f16c72'
down_revision: str | Sequence[str] | None = '750df89fef51'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('messages', sa.Column('media_object_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_messages_media_object_id',
        'messages',
        'media_objects',
        ['media_object_id'],
        ['id'],
        ondelete='SET NULL',
        use_alter=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_messages_media_object_id', 'messages', type_='foreignkey')
    op.drop_column('messages', 'media_object_id')
