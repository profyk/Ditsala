"""vip_multilingual

Revision ID: b7e3f1a9c2d4
Revises: a4f6c9d2e1b7
Create Date: 2026-09-19 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b7e3f1a9c2d4'
down_revision: str | Sequence[str] | None = 'a4f6c9d2e1b7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('user_language_preferences',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('preferred_language', sa.String(length=16), nullable=False),
    sa.Column('auto_detect_language', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('translate_incoming', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('translate_outgoing', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_language_preferences_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_user_language_preferences'))
    )

    op.create_table('vip_messages',
    sa.Column('conversation_id', sa.UUID(), nullable=False),
    sa.Column('sender_user_id', sa.UUID(), nullable=False),
    sa.Column('client_message_id', sa.String(length=128), nullable=False),
    sa.Column('original_text', sa.String(length=4000), nullable=False),
    sa.Column('original_language', sa.String(length=16), nullable=False),
    sa.Column('reply_to_message_id', sa.UUID(), nullable=True),
    sa.Column('edited_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_vip_messages_conversation_id_conversations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['reply_to_message_id'], ['vip_messages.id'], name=op.f('fk_vip_messages_reply_to_message_id_vip_messages'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['sender_user_id'], ['users.id'], name=op.f('fk_vip_messages_sender_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_vip_messages')),
    sa.UniqueConstraint('client_message_id', name=op.f('uq_vip_messages_client_message_id'))
    )
    op.create_index(op.f('ix_vip_messages_conversation_id'), 'vip_messages', ['conversation_id'], unique=False)

    op.create_table('vip_message_translations',
    sa.Column('vip_message_id', sa.UUID(), nullable=False),
    sa.Column('target_language', sa.String(length=16), nullable=False),
    sa.Column('translated_text', sa.String(length=4000), nullable=True),
    sa.Column('provider', sa.String(length=32), nullable=True),
    sa.Column('status', sa.Enum('pending', 'processing', 'completed', 'failed', name='translation_status', native_enum=False), server_default=sa.text("'pending'"), nullable=False),
    sa.Column('error_message', sa.String(length=500), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['vip_message_id'], ['vip_messages.id'], name=op.f('fk_vip_message_translations_vip_message_id_vip_messages'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_vip_message_translations'))
    )
    op.create_index(op.f('ix_vip_message_translations_vip_message_id'), 'vip_message_translations', ['vip_message_id'], unique=False)

    op.create_table('translation_requests',
    sa.Column('requested_by_user_id', sa.UUID(), nullable=False),
    sa.Column('context_type', sa.Enum('vip_message', 'interpreter', 'conference_caption', name='translation_context_type', native_enum=False), nullable=False),
    sa.Column('context_id', sa.UUID(), nullable=True),
    sa.Column('source_text', sa.String(length=4000), nullable=False),
    sa.Column('source_language', sa.String(length=16), nullable=True),
    sa.Column('target_language', sa.String(length=16), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=True),
    sa.Column('status', sa.Enum('pending', 'processing', 'completed', 'failed', name='translation_status', native_enum=False), server_default=sa.text("'pending'"), nullable=False),
    sa.Column('translated_text', sa.String(length=4000), nullable=True),
    sa.Column('error_message', sa.String(length=500), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['requested_by_user_id'], ['users.id'], name=op.f('fk_translation_requests_requested_by_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_translation_requests'))
    )
    op.create_index(op.f('ix_translation_requests_requested_by_user_id'), 'translation_requests', ['requested_by_user_id'], unique=False)
    op.create_index(op.f('ix_translation_requests_context_id'), 'translation_requests', ['context_id'], unique=False)
    op.create_index('ix_translation_requests_context_type_context_id', 'translation_requests', ['context_type', 'context_id'], unique=False)
    op.create_index('ix_translation_requests_requester_created', 'translation_requests', ['requested_by_user_id', 'created_at'], unique=False)

    op.create_table('interpreter_sessions',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('my_language', sa.String(length=16), nullable=False),
    sa.Column('other_language', sa.String(length=16), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_interpreter_sessions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_interpreter_sessions'))
    )
    op.create_index(op.f('ix_interpreter_sessions_user_id'), 'interpreter_sessions', ['user_id'], unique=False)

    op.create_table('conference_language_preferences',
    sa.Column('meeting_id', sa.UUID(), nullable=False),
    sa.Column('participant_id', sa.UUID(), nullable=False),
    sa.Column('language', sa.String(length=16), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['meeting_id'], ['meetings.id'], name=op.f('fk_conference_language_preferences_meeting_id_meetings'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['participant_id'], ['meeting_participants.id'], name=op.f('fk_conference_language_preferences_participant_id_meeting_participants'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_conference_language_preferences')),
    sa.UniqueConstraint('participant_id', name=op.f('uq_conference_language_preferences_participant_id'))
    )
    op.create_index(op.f('ix_conference_language_preferences_meeting_id'), 'conference_language_preferences', ['meeting_id'], unique=False)

    op.create_table('translation_usage',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('usage_date', sa.Date(), nullable=False),
    sa.Column('request_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('character_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_translation_usage_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_translation_usage')),
    sa.UniqueConstraint('user_id', 'usage_date', name='uq_translation_usage_user_date')
    )
    op.create_index(op.f('ix_translation_usage_user_id'), 'translation_usage', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_translation_usage_user_id'), table_name='translation_usage')
    op.drop_table('translation_usage')

    op.drop_index(op.f('ix_conference_language_preferences_meeting_id'), table_name='conference_language_preferences')
    op.drop_table('conference_language_preferences')

    op.drop_index(op.f('ix_interpreter_sessions_user_id'), table_name='interpreter_sessions')
    op.drop_table('interpreter_sessions')

    op.drop_index('ix_translation_requests_requester_created', table_name='translation_requests')
    op.drop_index('ix_translation_requests_context_type_context_id', table_name='translation_requests')
    op.drop_index(op.f('ix_translation_requests_context_id'), table_name='translation_requests')
    op.drop_index(op.f('ix_translation_requests_requested_by_user_id'), table_name='translation_requests')
    op.drop_table('translation_requests')

    op.drop_index(op.f('ix_vip_message_translations_vip_message_id'), table_name='vip_message_translations')
    op.drop_table('vip_message_translations')

    op.drop_index(op.f('ix_vip_messages_conversation_id'), table_name='vip_messages')
    op.drop_table('vip_messages')

    op.drop_table('user_language_preferences')
