import base64
import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.messaging import Message


def decode_b64(value: str) -> bytes:
    return base64.b64decode(value)


def encode_b64(value: bytes) -> str:
    return base64.b64encode(value).decode()


# --- key registration ---


class IdentityKeyRequest(BaseModel):
    public_identity_key: str  # base64
    registration_id: int


class SignedPrekeyRequest(BaseModel):
    key_id: int
    public_key: str  # base64
    signature: str  # base64


class OneTimePrekeyItem(BaseModel):
    key_id: int
    public_key: str  # base64


class OneTimePrekeysRequest(BaseModel):
    keys: list[OneTimePrekeyItem] = Field(min_length=1, max_length=100)


class PrekeyBundleResponse(BaseModel):
    identity_key: str  # base64
    registration_id: int
    signed_prekey_id: int
    signed_prekey_public: str  # base64
    signed_prekey_signature: str  # base64
    one_time_prekey_id: int | None
    one_time_prekey_public: str | None  # base64


# --- conversations ---


class StartDirectConversationRequest(BaseModel):
    other_user_id: uuid.UUID


class CreateGroupConversationRequest(BaseModel):
    member_ids: list[uuid.UUID] = Field(min_length=1, max_length=250)


class ConversationResponse(BaseModel):
    id: uuid.UUID
    type: str
    disappearing_timer_seconds: int | None

    model_config = {"from_attributes": True}


class SetDisappearingTimerRequest(BaseModel):
    seconds: int | None = Field(default=None, ge=1, le=31_536_000)  # up to 1 year


class SetMutedRequest(BaseModel):
    muted_until: datetime | None


class SetFlagRequest(BaseModel):
    value: bool


# --- messages ---


class SendMessageRequest(BaseModel):
    ciphertext: str  # base64
    content_type: str = Field(pattern="^(text|media|voice_note|reaction|system)$")
    client_message_id: str = Field(min_length=1, max_length=128)
    reply_to_message_id: uuid.UUID | None = None


class MessageResponse(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_device_id: uuid.UUID | None
    ciphertext: str  # base64
    content_type: str
    client_message_id: str
    reply_to_message_id: uuid.UUID | None
    edited_at: datetime | None
    deleted_at: datetime | None
    expires_at: datetime | None
    created_at: datetime

    @classmethod
    def from_model(cls, message: Message) -> "MessageResponse":
        return cls(
            id=message.id,
            conversation_id=message.conversation_id,
            sender_device_id=message.sender_device_id,
            ciphertext=encode_b64(message.ciphertext),
            content_type=message.content_type,
            client_message_id=message.client_message_id,
            reply_to_message_id=message.reply_to_message_id,
            edited_at=message.edited_at,
            deleted_at=message.deleted_at,
            expires_at=message.expires_at,
            created_at=message.created_at,
        )


class EditMessageRequest(BaseModel):
    ciphertext: str  # base64


class ReceiptRequest(BaseModel):
    status: str = Field(pattern="^(delivered|read)$")


# --- groups: Sender Keys ---


class SenderKeyRequest(BaseModel):
    distribution_message_ref: str  # base64


class SenderKeyResponse(BaseModel):
    device_id: uuid.UUID
    distribution_message_ref: str  # base64


# --- media ---


class MediaUploadRequest(BaseModel):
    content_hash: str = Field(min_length=1, max_length=128)
    encrypted_size_bytes: int = Field(gt=0)
    content_type: str = Field(min_length=1, max_length=128)


class MediaUploadResponse(BaseModel):
    media_object_id: uuid.UUID
    upload_url: str


class MediaDownloadResponse(BaseModel):
    download_url: str
