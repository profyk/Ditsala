import uuid

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
