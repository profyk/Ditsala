import uuid

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

    async def list_for_conversation(self, conversation_id: uuid.UUID) -> list[Message]:
        result = await self.session.execute(
            self._select().where(Message.conversation_id == conversation_id)
        )
        return list(result.scalars().all())


class MessageReceiptRepository(Repository[MessageReceipt]):
    model = MessageReceipt


class MediaObjectRepository(Repository[MediaObject]):
    model = MediaObject
