"""
Admin messaging-governance response/request shapes — same "third,
admin-only view" reasoning as `app/schemas/admin_calls.py`/
`admin_meetings.py`. See `app/domain/admin/messaging_governance.py`.

Every field here is metadata (ids, counts, timestamps, roles) — none of
these ever carry `ciphertext`, by construction, not merely by omission.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.admin.messaging_governance import (
    ConversationDetail,
    ConversationMemberSummary,
    ConversationWithCounts,
    MessageContext,
)


class AdminConversationSummaryResponse(BaseModel):
    id: uuid.UUID
    type: str
    title: str | None
    member_count: int
    message_count: int
    created_at: datetime

    @classmethod
    def from_domain(cls, item: ConversationWithCounts) -> "AdminConversationSummaryResponse":
        return cls(
            id=item.conversation.id,
            type=item.conversation.type,
            title=item.conversation.title,
            member_count=item.member_count,
            message_count=item.message_count,
            created_at=item.conversation.created_at,
        )


class AdminConversationListResponse(BaseModel):
    conversations: list[AdminConversationSummaryResponse]
    total: int


class AdminConversationMemberResponse(BaseModel):
    user_id: uuid.UUID
    display_name: str
    role: str
    joined_at: datetime

    @classmethod
    def from_domain(cls, item: ConversationMemberSummary) -> "AdminConversationMemberResponse":
        return cls(
            user_id=item.user_id, display_name=item.display_name, role=item.role,
            joined_at=item.joined_at,
        )


class AdminConversationDetailResponse(BaseModel):
    id: uuid.UUID
    type: str
    title: str | None
    created_at: datetime
    message_count: int
    members: list[AdminConversationMemberResponse]

    @classmethod
    def from_domain(cls, detail: ConversationDetail) -> "AdminConversationDetailResponse":
        return cls(
            id=detail.conversation.id,
            type=detail.conversation.type,
            title=detail.conversation.title,
            created_at=detail.conversation.created_at,
            message_count=detail.message_count,
            members=[AdminConversationMemberResponse.from_domain(m) for m in detail.members],
        )


class AdminMessageContextResponse(BaseModel):
    """Backs a Reports & Moderation reviewer looking up a message-level
    report's `context_ref` — everything needed to act on it, nothing
    that requires decrypting anything (there is no `ciphertext` field
    here at all)."""

    message_id: uuid.UUID
    conversation_id: uuid.UUID
    sender_user_id: uuid.UUID | None
    content_type: str
    created_at: datetime
    deleted_at: datetime | None

    @classmethod
    def from_domain(cls, context: MessageContext) -> "AdminMessageContextResponse":
        return cls(
            message_id=context.message_id,
            conversation_id=context.conversation_id,
            sender_user_id=context.sender_user_id,
            content_type=context.content_type,
            created_at=context.created_at,
            deleted_at=context.deleted_at,
        )


class AdminRemoveMemberRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class AdminDeleteMessageRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
