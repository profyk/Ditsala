import uuid

from sqlalchemy import func, select

from app.models.messaging import Conversation, ConversationMember
from app.repositories.base import Repository


class ConversationRepository(Repository[Conversation]):
    model = Conversation

    async def list_recent(self, *, limit: int = 100, offset: int = 0) -> list[Conversation]:
        """Platform-wide, newest first — the admin governance equivalent
        of `list_for_user`'s per-user scoping (there is no per-user
        filter here at all, deliberately: this is the first place in
        this codebase that lists conversations without one)."""
        result = await self.session.execute(
            self._select().order_by(Conversation.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def count_all(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(Conversation))
        return result.scalar_one()


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
        return await self.find_conversation_id(user_a, user_b, conversation_type="direct")

    async def find_conversation_id(
        self, user_a: uuid.UUID, user_b: uuid.UUID, *, conversation_type: str
    ) -> uuid.UUID | None:
        """Same idempotent-lookup shape as `find_direct_conversation_id`,
        generalized so VIP multilingual chat (`conversation_type=
        "vip_multilingual"`) can reuse it instead of duplicating the
        query — a `direct` and a `vip_multilingual` thread between the
        same two people are never mistaken for each other."""
        a_ids_stmt = (
            select(ConversationMember.conversation_id)
            .join(Conversation, Conversation.id == ConversationMember.conversation_id)
            .where(ConversationMember.user_id == user_a, Conversation.type == conversation_type)
        )
        b_ids_stmt = (
            select(ConversationMember.conversation_id)
            .join(Conversation, Conversation.id == ConversationMember.conversation_id)
            .where(ConversationMember.user_id == user_b, Conversation.type == conversation_type)
        )
        a_ids = {row[0] for row in (await self.session.execute(a_ids_stmt)).all()}
        b_ids = {row[0] for row in (await self.session.execute(b_ids_stmt)).all()}
        shared = a_ids & b_ids
        return next(iter(shared), None)
