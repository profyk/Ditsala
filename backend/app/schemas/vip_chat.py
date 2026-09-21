import uuid

from pydantic import BaseModel, Field

from app.domain.vip_chat.service import VipMessageWithTranslation
from app.models.messaging import Conversation


class StartVipConversationRequest(BaseModel):
    other_user_id: uuid.UUID


class VipConversationResponse(BaseModel):
    id: uuid.UUID
    created_by: uuid.UUID | None
    created_at: str

    @classmethod
    def from_conversation(cls, conversation: Conversation) -> "VipConversationResponse":
        return cls(
            id=conversation.id,
            created_by=conversation.created_by,
            created_at=conversation.created_at.isoformat(),
        )


class SendVipMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    client_message_id: str = Field(min_length=1, max_length=128)


class VipMessageTranslationResponse(BaseModel):
    target_language: str
    translated_text: str | None
    provider: str | None
    status: str
    error_message: str | None


class VipMessageResponse(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_user_id: uuid.UUID
    original_text: str
    original_language: str
    created_at: str
    translation: VipMessageTranslationResponse | None

    @classmethod
    def from_domain(cls, item: VipMessageWithTranslation) -> "VipMessageResponse":
        return cls(
            id=item.message.id,
            conversation_id=item.message.conversation_id,
            sender_user_id=item.message.sender_user_id,
            original_text=item.message.original_text,
            original_language=item.message.original_language,
            created_at=item.message.created_at.isoformat(),
            translation=(
                VipMessageTranslationResponse(
                    target_language=item.translation.target_language,
                    translated_text=item.translation.translated_text,
                    provider=item.translation.provider,
                    status=item.translation.status,
                    error_message=item.translation.error_message,
                )
                if item.translation is not None
                else None
            ),
        )
