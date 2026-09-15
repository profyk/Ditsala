import uuid

from sqlalchemy import select

from app.models.messaging import Conversation, ConversationMember
from app.repositories.base import Repository


class ConversationRepository(Repository[Conversation]):
    model = Conversation


class ConversationMemberRepository(Repository[ConversationMember]):
    model = ConversationMember

    async def list_for_conversation(
        self, conversation_id: uuid.UUID
    ) -> list[ConversationMember]:
        result = await self.session.execute(
            self._select().where(ConversationMember.conversation_id == conversation_id)
        )
        return list(result.scalars().all())

    async def list_for_user(self, user_id: uuid.UUID) -> list[ConversationMember]:
        result = await self.session.execute(
            self._select().where(ConversationMember.user_id == user_id)
        )
        return list(result.scalars().all())

    async def get_membership(
        self, conversation_id: uuid.UUID, user_id: uuid.UUID
    ) -> ConversationMember | None:
        result = await self.session.execute(
            self._select().where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def find_direct_conversation_id(
        self, user_a: uuid.UUID, user_b: uuid.UUID
    ) -> uuid.UUID | None:
        """An existing 1:1 (type='direct') conversation both users already
        belong to, if any — used so `start_direct_conversation` is
        idempotent rather than creating a fresh conversation every time
        two people message. Restricted to `direct` type so a group both
        happen to share is never mistaken for their 1:1 thread."""
        a_ids_stmt = (
            select(ConversationMember.conversation_id)
            .join(Conversation, Conversation.id == ConversationMember.conversation_id)
            .where(ConversationMember.user_id == user_a, Conversation.type == "direct")
        )
        b_ids_stmt = (
            select(ConversationMember.conversation_id)
            .join(Conversation, Conversation.id == ConversationMember.conversation_id)
            .where(ConversationMember.user_id == user_b, Conversation.type == "direct")
        )
        a_ids = {row[0] for row in (await self.session.execute(a_ids_stmt)).all()}
        b_ids = {row[0] for row in (await self.session.execute(b_ids_stmt)).all()}
        shared = a_ids & b_ids
        return next(iter(shared), None)
