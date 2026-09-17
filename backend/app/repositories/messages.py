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
    ) -> list[Message]:
        stmt = self._select().where(Message.conversation_id == conversation_id)
        if before is not None:
            stmt = stmt.where(Message.created_at < before)
        stmt = stmt.order_by(Message.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_for_conversation(self, conversation_id: uuid.UUID) -> Message | None:
        result = await self.session.execute(
            self._select()
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
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
