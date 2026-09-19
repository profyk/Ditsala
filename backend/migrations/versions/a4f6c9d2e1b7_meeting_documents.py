"""meeting_documents

Revision ID: a4f6c9d2e1b7
Revises: c1c1b8e6f0a2
Create Date: 2026-09-19 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a4f6c9d2e1b7'
down_revision: str | Sequence[str] | None = 'c1c1b8e6f0a2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('meeting_documents',
    sa.Column('meeting_id', sa.UUID(), nullable=False),
    sa.Column('uploaded_by_participant_id', sa.UUID(), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('content_type', sa.String(length=128), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('storage_key', sa.String(length=512), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['meeting_id'], ['meetings.id'], name=op.f('fk_meeting_documents_meeting_id_meetings'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['uploaded_by_participant_id'], ['meeting_participants.id'], name=op.f('fk_meeting_documents_uploaded_by_participant_id_meeting_participants'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_meeting_documents'))
    )
    op.create_index(op.f('ix_meeting_documents_meeting_id'), 'meeting_documents', ['meeting_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_meeting_documents_meeting_id'), table_name='meeting_documents')
    op.drop_table('meeting_documents')
