"""
Admin visibility and control over messaging conversations, platform-
wide — the same new-capability shape as `AdminMeetingGovernanceService`/
`AdminCallGovernanceService`: every conversation-scoped action elsewhere
in this codebase (`MessagingService`) is member-scoped, admin previously
had zero visibility into messaging at all, not even metadata. Kept as
its own service, same precedent `KycReviewService`/the meetings/calls
governance services already set.

Every field this service returns is metadata a conversation's own
members can already see via `list_conversation_members`/`list_messages`'s
non-content fields (who's in a conversation, when, how many messages) —
§7.3's "no admin path can retrieve decrypted content" is not weakened by
any of this. `ciphertext` is never read, returned, or logged here.

Mutations (remove a member, delete a message) delegate to
`MessagingService.admin_remove_member`/`admin_delete_message` — the
actual mutation logic stays in one place — and add the admin-specific
concern: audit logging via the same generic `audit_log` table every
other admin mutation in this codebase uses.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.domain.messaging.service import MessagingError, MessagingService
from app.models.admin import AuditLog
from app.models.messaging import Conversation, Message
from app.repositories.admin import AuditLogRepository
from app.repositories.conversations import ConversationMemberRepository, ConversationRepository
from app.repositories.devices import DeviceRepository
from app.repositories.messages import MessageRepository
from app.repositories.users import UserRepository


class MessagingGovernanceError(Exception):
    """Raised for governance preconditions a caller should turn into a 4xx, not a 500."""


@dataclass(frozen=True)
class ConversationWithCounts:
    """A conversation plus the two counts an admin list view actually
    needs at a glance — computed here, same shape as
    `AdminMeetingGovernanceService`'s `MeetingWithHostContext`."""

    conversation: Conversation
    member_count: int
    message_count: int


@dataclass(frozen=True)
class ConversationMemberSummary:
    user_id: uuid.UUID
    display_name: str
    role: str
    joined_at: datetime


@dataclass(frozen=True)
class ConversationDetail:
    conversation: Conversation
    members: list[ConversationMemberSummary]
    message_count: int


@dataclass(frozen=True)
class MessageContext:
    """What a moderator reviewing a message-level report actually needs
    — everything except the one thing they structurally can't have.
    `context_ref` on a `Report` is a message id; this resolves it to
    enough metadata to act on (which conversation, who sent it, when,
    whether it's already gone) without ever touching `ciphertext`."""

    message_id: uuid.UUID
    conversation_id: uuid.UUID
    sender_user_id: uuid.UUID | None
    content_type: str
    created_at: datetime
    deleted_at: datetime | None


class AdminMessagingGovernanceService:
    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        conversation_members: ConversationMemberRepository,
        messages: MessageRepository,
        users: UserRepository,
        devices: DeviceRepository,
        messaging_service: MessagingService,
        audit_log: AuditLogRepository,
    ) -> None:
        self._conversations = conversations
        self._conversation_members = conversation_members
        self._messages = messages
        self._users = users
        self._devices = devices
        self._messaging_service = messaging_service
        self._audit_log = audit_log

    async def _log(
        self,
        admin_id: uuid.UUID,
        action: str,
        *,
        target_id: uuid.UUID,
        metadata_json: dict[str, Any] | None = None,
    ) -> None:
        await self._audit_log.add(
            AuditLog(
                created_at=datetime.now(UTC),
                actor_type="admin",
                actor_id=admin_id,
                action=action,
                target_type="conversation",
                target_id=target_id,
                metadata_json=metadata_json,
            )
        )

    async def list_conversations(
        self, *, limit: int = 100, offset: int = 0
    ) -> list[ConversationWithCounts]:
        conversations = await self._conversations.list_recent(limit=limit, offset=offset)
        result: list[ConversationWithCounts] = []
        for conversation in conversations:
            members = await self._conversation_members.list_for_conversation(conversation.id)
            message_count = await self._messages.count_for_conversation(conversation.id)
            result.append(
                ConversationWithCounts(
                    conversation=conversation,
                    member_count=len(members),
                    message_count=message_count,
                )
            )
        return result

    async def count_conversations(self) -> int:
        return await self._conversations.count_all()

    async def get_conversation(self, conversation_id: uuid.UUID) -> ConversationDetail:
        conversation = await self._conversations.get(conversation_id)
        if conversation is None:
            raise MessagingGovernanceError("No such conversation.")
        members = await self._conversation_members.list_for_conversation(conversation_id)
        summaries = []
        for member in members:
            user = await self._users.get(member.user_id)
            summaries.append(
                ConversationMemberSummary(
                    user_id=member.user_id,
                    display_name=user.display_name if user is not None else "Unknown",
                    role=member.role,
                    joined_at=member.joined_at,
                )
            )
        message_count = await self._messages.count_for_conversation(conversation_id)
        return ConversationDetail(
            conversation=conversation, members=summaries, message_count=message_count
        )

    async def get_message_context(self, message_id: uuid.UUID) -> MessageContext:
        message = await self._messages.get(message_id)
        if message is None:
            raise MessagingGovernanceError("No such message.")
        sender_user_id: uuid.UUID | None = None
        if message.sender_device_id is not None:
            device = await self._devices.get(message.sender_device_id)
            sender_user_id = device.user_id if device is not None else None
        return MessageContext(
            message_id=message.id,
            conversation_id=message.conversation_id,
            sender_user_id=sender_user_id,
            content_type=message.content_type,
            created_at=message.created_at,
            deleted_at=message.deleted_at,
        )

    async def remove_member(
        self,
        *,
        admin_id: uuid.UUID,
        conversation_id: uuid.UUID,
        target_user_id: uuid.UUID,
        reason: str,
    ) -> None:
        try:
            await self._messaging_service.admin_remove_member(
                conversation_id=conversation_id, target_user_id=target_user_id
            )
        except MessagingError as exc:
            raise MessagingGovernanceError(str(exc)) from exc
        await self._log(
            admin_id,
            "admin.conversation.member_removed",
            target_id=conversation_id,
            metadata_json={"target_user_id": str(target_user_id), "reason": reason},
        )

    async def delete_message(
        self, *, admin_id: uuid.UUID, message_id: uuid.UUID, reason: str
    ) -> Message:
        try:
            message = await self._messaging_service.admin_delete_message(message_id=message_id)
        except MessagingError as exc:
            raise MessagingGovernanceError(str(exc)) from exc
        await self._log(
            admin_id,
            "admin.message.deleted",
            target_id=message.conversation_id,
            metadata_json={"message_id": str(message_id), "reason": reason},
        )
        return message
