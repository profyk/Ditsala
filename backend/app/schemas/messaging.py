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


class PrimaryDeviceResponse(BaseModel):
    device_id: uuid.UUID


class UserDevicesResponse(BaseModel):
    device_ids: list[uuid.UUID]


# --- conversations ---


class StartDirectConversationRequest(BaseModel):
    other_user_id: uuid.UUID


class CreateGroupConversationRequest(BaseModel):
    member_ids: list[uuid.UUID] = Field(min_length=1, max_length=250)
    title: str | None = Field(default=None, max_length=200)


class RenameGroupConversationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ConversationResponse(BaseModel):
    id: uuid.UUID
    type: str
    title: str | None
    disappearing_timer_seconds: int | None
    last_message_at: datetime | None = None
    # The calling user's own membership state — muted_until/archived_at/
    # pinned_at have always been real columns on conversation_members,
    # just never read back anywhere (setMuted/setArchived/setPinned were
    # write-only). Deliberately this user's own values, not a global
    # conversation property — muting/archiving/pinning is personal.
    muted_until: datetime | None = None
    archived: bool = False
    pinned: bool = False

    model_config = {"from_attributes": True}


class ConversationMemberResponse(BaseModel):
    user_id: uuid.UUID
    display_name: str
    avatar_url: str | None
    role: str
    joined_at: datetime

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
    recipient_device_id: uuid.UUID
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
