import uuid
from datetime import datetime

from app.models.messaging import MediaObject, Message, MessageReceipt
from app.repositories.base import Repository


class MessageRepository(Repository[Message]):
    model = Message

    async def get_by_client_message_id(self, client_message_id: str) -> Message | None:
        """Idempotency check — see docs/DITSALA_MASTER_SPEC.md §18-21."""
        result = await self.session.execute(
            self._select().where(Message.client_message_id == client_message_id)
        )
        return result.scalar_one_or_none()

    async def list_for_conversation(
        self,
        conversation_id: uuid.UUID,
        *,
        before: datetime | None = None,
        limit: int = 50,
        cleared_at: datetime | None = None,
    ) -> list[Message]:
        stmt = self._select().where(Message.conversation_id == conversation_id)
        if before is not None:
            stmt = stmt.where(Message.created_at < before)
        # "Clear chat for me" (§ chat rebuild Phase 6) — a per-user cursor
        # on the calling member's own row, not a real delete: everything
        # at or before it is hidden from them only, going forward.
        # `created_at` is `timestamp without time zone` (TimestampMixin) —
        # comparing it against a tz-aware value raises an asyncpg
        # DataError (same class of bug Phase 7 already hit and fixed
        # elsewhere), so this strips tzinfo the same way.
        if cleared_at is not None:
            stmt = stmt.where(Message.created_at > cleared_at.replace(tzinfo=None))
        stmt = stmt.order_by(Message.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_for_conversation(self, conversation_id: uuid.UUID) -> Message | None:
        """Drives `ConversationSummary.last_message_at` — the list
        screen's sort order and "last message" preview. Real gap this
        excludes: without filtering `content_type != "reaction"`,
        reacting to an old message would make a conversation jump to the
        top of the list showing "Reaction" as its preview, even though
        nothing about the actual conversation content changed."""
        result = await self.session.execute(
            self._select()
            .where(Message.conversation_id == conversation_id, Message.content_type != "reaction")
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_pinned_for_conversation(self, conversation_id: uuid.UUID) -> Message | None:
        """The single most-recently-pinned, still-visible message in a
        conversation — a banner shows just this one, matching how the
        reference design's "pinned message" UI works (last pinned wins,
        not a list)."""
        result = await self.session.execute(
            self._select()
            .where(
                Message.conversation_id == conversation_id,
                Message.pinned_at.is_not(None),
                Message.deleted_at.is_(None),
            )
            .order_by(Message.pinned_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_expired(self, *, now: datetime) -> list[Message]:
        """Disappearing messages (§21) due for the retention sweep —
        deliberately excludes already-deleted rows (nothing to purge twice)."""
        result = await self.session.execute(
            self._select().where(
                Message.expires_at.is_not(None),
                Message.expires_at < now,
                Message.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())


class MessageReceiptRepository(Repository[MessageReceipt]):
    model = MessageReceipt

    async def get_for_message_and_user(
        self, message_id: uuid.UUID, user_id: uuid.UUID, status: str
    ) -> MessageReceipt | None:
        result = await self.session.execute(
            self._select().where(
                MessageReceipt.message_id == message_id,
                MessageReceipt.user_id == user_id,
                MessageReceipt.status == status,
            )
        )
        return result.scalar_one_or_none()


class MediaObjectRepository(Repository[MediaObject]):
    model = MediaObject
