"""
E2EE messaging — docs/DITSALA_MASTER_SPEC.md §6, §18-21. The backend
relays ciphertext and key material only; it never decrypts anything and
never could (§7.3). Key registration/prekey-bundle retrieval here is the
persistence + distribution half of the Signal Protocol handshake — the
other half (actually running X3DH/Double Ratchet/Sender Keys) is the
native libsignal module, which is not built in this environment (no
native iOS/Android toolchain — see docs/adr/0005-e2ee-native-module-gap.md
and docs/SECURITY_GAPS.md). Everything in this file is real, working,
tested code regardless of that gap: it's what the native module will
call once it exists.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.domain.messaging.interfaces import StorageProvider
from app.models.crypto import IdentityKey, OneTimePrekey, SenderKey, SignedPrekey
from app.models.devices import Device
from app.models.messaging import (
    Conversation,
    ConversationMember,
    MediaObject,
    Message,
    MessageReceipt,
)
from app.repositories.circle import BlockRepository, ContactRepository
from app.repositories.conversations import ConversationMemberRepository, ConversationRepository
from app.repositories.crypto import (
    IdentityKeyRepository,
    OneTimePrekeyRepository,
    SenderKeyRepository,
    SignedPrekeyRepository,
)
from app.repositories.devices import DeviceRepository
from app.repositories.messages import (
    MediaObjectRepository,
    MessageReceiptRepository,
    MessageRepository,
)
from app.repositories.users import UserRepository
from app.services.realtime.websocket_manager import ConnectionManager

MAX_MEDIA_SIZE_BYTES = 100 * 1024 * 1024  # 100MB, client-side-encrypted


class MessagingError(Exception):
    """Raised for messaging preconditions a caller should turn into a 4xx, not a 500."""


@dataclass(frozen=True)
class ConversationSummary:
    conversation: Conversation
    last_message_at: datetime | None


@dataclass(frozen=True)
class EnrichedMember:
    user_id: uuid.UUID
    display_name: str
    avatar_url: str | None
    role: str
    joined_at: datetime


@dataclass(frozen=True)
class PrekeyBundle:
    identity_key: bytes
    registration_id: int
    signed_prekey_id: int
    signed_prekey_public: bytes
    signed_prekey_signature: bytes
    one_time_prekey_id: int | None
    one_time_prekey_public: bytes | None


class MessagingService:
    def __init__(
        self,
        *,
        identity_keys: IdentityKeyRepository,
        signed_prekeys: SignedPrekeyRepository,
        one_time_prekeys: OneTimePrekeyRepository,
        sender_keys: SenderKeyRepository,
        conversations: ConversationRepository,
        conversation_members: ConversationMemberRepository,
        messages: MessageRepository,
        message_receipts: MessageReceiptRepository,
        media_objects: MediaObjectRepository,
        devices: DeviceRepository,
        blocks: BlockRepository,
        contacts: ContactRepository,
        users: UserRepository,
        storage_provider: StorageProvider,
        connection_manager: ConnectionManager,
    ) -> None:
        self._identity_keys = identity_keys
        self._signed_prekeys = signed_prekeys
        self._one_time_prekeys = one_time_prekeys
        self._sender_keys = sender_keys
        self._conversations = conversations
        self._conversation_members = conversation_members
        self._messages = messages
        self._message_receipts = message_receipts
        self._media_objects = media_objects
        self._devices = devices
        self._blocks = blocks
        self._users = users
        self._contacts = contacts
        self._storage = storage_provider
        self._connections = connection_manager

    # --- §6: key registration ---

    async def register_identity_key(
        self, device: Device, *, public_identity_key: bytes, registration_id: int
    ) -> IdentityKey:
        existing = await self._identity_keys.get_for_device(device.id)
        if existing is not None:
            if existing.public_identity_key != public_identity_key:
                # A genuine re-key (reinstall, new device), not an idempotent
                # resend — §23 requires re-verification, never silent trust.
                await self._contacts.demote_trusted_contacts_of(device.user_id)
            existing.public_identity_key = public_identity_key
            existing.registration_id = registration_id
            return existing
        return await self._identity_keys.add(
            IdentityKey(
                user_id=device.user_id,
                device_id=device.id,
                public_identity_key=public_identity_key,
                registration_id=registration_id,
            )
        )

    async def upload_signed_prekey(
        self, device: Device, *, key_id: int, public_key: bytes, signature: bytes
    ) -> SignedPrekey:
        current = await self._signed_prekeys.get_current_for_device(device.id)
        if current is not None:
            current.rotated_at = datetime.now(UTC)
        return await self._signed_prekeys.add(
            SignedPrekey(
                device_id=device.id,
                key_id=key_id,
                public_key=public_key,
                signature=signature,
                uploaded_at=datetime.now(UTC),
            )
        )

    async def upload_one_time_prekeys(
        self, device: Device, *, keys: list[tuple[int, bytes]]
    ) -> list[OneTimePrekey]:
        return [
            await self._one_time_prekeys.add(
                OneTimePrekey(device_id=device.id, key_id=key_id, public_key=public_key)
            )
            for key_id, public_key in keys
        ]

    async def get_prekey_bundle(self, *, user_id: uuid.UUID, device_id: uuid.UUID) -> PrekeyBundle:
        identity_key = await self._identity_keys.get_for_device(device_id)
        signed_prekey = await self._signed_prekeys.get_current_for_device(device_id)
        if identity_key is None or identity_key.user_id != user_id or signed_prekey is None:
            raise MessagingError("This device has not completed key registration.")

        one_time_prekey = await self._one_time_prekeys.claim_one(device_id)
        if one_time_prekey is not None:
            one_time_prekey.consumed_at = datetime.now(UTC)

        return PrekeyBundle(
            identity_key=identity_key.public_identity_key,
            registration_id=identity_key.registration_id,
            signed_prekey_id=signed_prekey.key_id,
            signed_prekey_public=signed_prekey.public_key,
            signed_prekey_signature=signed_prekey.signature,
            one_time_prekey_id=one_time_prekey.key_id if one_time_prekey else None,
            one_time_prekey_public=one_time_prekey.public_key if one_time_prekey else None,
        )

    async def get_primary_device_id(self, user_id: uuid.UUID) -> uuid.UUID:
        identity_key = await self._identity_keys.get_most_recent_for_user(user_id)
        if identity_key is None:
            raise MessagingError("This user has not completed key registration on any device.")
        return identity_key.device_id

    async def list_device_ids_for_user(self, user_id: uuid.UUID) -> list[uuid.UUID]:
        """Every device of this user with completed key registration —
        real multi-device fan-out (docs/adr/0013) distributes a Sender
        Key to each one, not just the most recent."""
        identity_keys = await self._identity_keys.list_for_user(user_id)
        return [k.device_id for k in identity_keys]

    # --- conversations ---

    async def start_direct_conversation(
        self, current_user_id: uuid.UUID, other_user_id: uuid.UUID
    ) -> Conversation:
        if current_user_id == other_user_id:
            raise MessagingError("Cannot start a conversation with yourself.")
        if await self._blocks.exists(other_user_id, current_user_id) or await self._blocks.exists(
            current_user_id, other_user_id
        ):
            raise MessagingError("Cannot message a blocked contact.")

        existing_id = await self._conversation_members.find_direct_conversation_id(
            current_user_id, other_user_id
        )
        if existing_id is not None:
            existing = await self._conversations.get(existing_id)
            assert existing is not None
            return existing

        contact = await self._contacts.get_by_pair(current_user_id, other_user_id)
        if contact is None or contact.tier not in ("verified", "trusted"):
            raise MessagingError(
                "Direct messaging requires an accepted Circle contact request first."
            )

        conversation = await self._conversations.add(
            Conversation(type="direct", created_by=current_user_id)
        )
        now = datetime.now(UTC)
        for uid in (current_user_id, other_user_id):
            await self._conversation_members.add(
                ConversationMember(conversation_id=conversation.id, user_id=uid, joined_at=now)
            )
        return conversation

    async def create_group_conversation(
        self, creator_id: uuid.UUID, member_ids: list[uuid.UUID], *, title: str | None = None
    ) -> Conversation:
        # Same Circle-tier gate as a direct conversation (§22) — group
        # messaging isn't exempt from "an accepted Circle contact
        # request first" just because it's multi-party.
        for member_id in member_ids:
            if member_id == creator_id:
                continue
            contact = await self._contacts.get_by_pair(creator_id, member_id)
            if contact is None or contact.tier not in ("verified", "trusted"):
                raise MessagingError(
                    "Every group member must be an accepted Circle contact first."
                )

        conversation = await self._conversations.add(
            Conversation(type="group", created_by=creator_id, title=title)
        )
        now = datetime.now(UTC)
        await self._conversation_members.add(
            ConversationMember(
                conversation_id=conversation.id, user_id=creator_id, role="admin", joined_at=now
            )
        )
        for member_id in member_ids:
            if member_id == creator_id:
                continue
            await self._conversation_members.add(
                ConversationMember(
                    conversation_id=conversation.id, user_id=member_id, joined_at=now
                )
            )
        return conversation

    async def list_conversations(self, user_id: uuid.UUID) -> list[ConversationSummary]:
        memberships = await self._conversation_members.list_for_user(user_id)
        summaries = []
        for membership in memberships:
            conversation = await self._conversations.get(membership.conversation_id)
            if conversation is None:
                continue
            latest = await self._messages.get_latest_for_conversation(conversation.id)
            summaries.append(
                ConversationSummary(
                    conversation=conversation,
                    last_message_at=latest.created_at if latest else None,
                )
            )
        return summaries

    async def rename_group_conversation(
        self, *, user_id: uuid.UUID, conversation_id: uuid.UUID, title: str
    ) -> Conversation:
        membership = await self._require_membership(conversation_id, user_id)
        conversation = await self._conversations.get(conversation_id)
        if conversation is None:
            raise MessagingError("No such conversation.")
        if conversation.type != "group":
            raise MessagingError("Only group conversations can be renamed.")
        if membership.role != "admin":
            raise MessagingError("Only a group admin can rename this conversation.")
        conversation.title = title
        return conversation

    async def list_conversation_members(
        self, *, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> list[EnrichedMember]:
        await self._require_membership(conversation_id, user_id)
        members = await self._conversation_members.list_for_conversation(conversation_id)
        enriched = []
        for member in members:
            member_user = await self._users.get(member.user_id)
            if member_user is None:
                continue
            avatar_url = (
                await self._storage.create_download_url(key=member_user.avatar_key)
                if member_user.avatar_key
                else None
            )
            enriched.append(
                EnrichedMember(
                    user_id=member.user_id,
                    display_name=member_user.display_name,
                    avatar_url=avatar_url,
                    role=member.role,
                    joined_at=member.joined_at,
                )
            )
        return enriched

    async def _require_membership(
        self, conversation_id: uuid.UUID, user_id: uuid.UUID
    ) -> ConversationMember:
        membership = await self._conversation_members.get_membership(conversation_id, user_id)
        if membership is None:
            raise MessagingError("Not a member of this conversation.")
        return membership

    # --- messages ---

    async def send_message(
        self,
        *,
        sender_user_id: uuid.UUID,
        sender_device_id: uuid.UUID,
        conversation_id: uuid.UUID,
        ciphertext: bytes,
        content_type: str,
        client_message_id: str,
        reply_to_message_id: uuid.UUID | None = None,
    ) -> Message:
        await self._require_membership(conversation_id, sender_user_id)

        existing = await self._messages.get_by_client_message_id(client_message_id)
        if existing is not None:
            return existing  # idempotent resend

        conversation = await self._conversations.get(conversation_id)
        assert conversation is not None
        expires_at = None
        if conversation.disappearing_timer_seconds:
            expires_at = datetime.now(UTC) + timedelta(
                seconds=conversation.disappearing_timer_seconds
            )

        message = await self._messages.add(
            Message(
                conversation_id=conversation_id,
                sender_device_id=sender_device_id,
                ciphertext=ciphertext,
                content_type=content_type,
                client_message_id=client_message_id,
                reply_to_message_id=reply_to_message_id,
                expires_at=expires_at,
            )
        )
        await self._notify_conversation(
            conversation_id,
            {"type": "message.new", "message_id": str(message.id)},
            exclude_device_id=sender_device_id,
        )
        return message

    async def list_messages(
        self, *, user_id: uuid.UUID, conversation_id: uuid.UUID,
        before: datetime | None = None, limit: int = 50,
    ) -> list[Message]:
        await self._require_membership(conversation_id, user_id)
        return await self._messages.list_for_conversation(
            conversation_id, before=before, limit=limit
        )

    async def edit_message(
        self, *, user_id: uuid.UUID, message_id: uuid.UUID, new_ciphertext: bytes
    ) -> Message:
        message = await self._messages.get(message_id)
        if message is None:
            raise MessagingError("Unknown message.")
        await self._require_own_message(message, user_id)
        message.ciphertext = new_ciphertext
        message.edited_at = datetime.now(UTC)
        await self._notify_conversation(
            message.conversation_id, {"type": "message.edited", "message_id": str(message.id)}
        )
        return message

    async def delete_message(self, *, user_id: uuid.UUID, message_id: uuid.UUID) -> None:
        message = await self._messages.get(message_id)
        if message is None:
            raise MessagingError("Unknown message.")
        await self._require_own_message(message, user_id)
        message.deleted_at = datetime.now(UTC)
        message.ciphertext = b""
        await self._notify_conversation(
            message.conversation_id, {"type": "message.deleted", "message_id": str(message.id)}
        )

    async def _require_own_message(self, message: Message, user_id: uuid.UUID) -> None:
        await self._require_membership(message.conversation_id, user_id)
        if message.sender_device_id is None:
            raise MessagingError("Cannot modify this message.")
        device = await self._devices.get(message.sender_device_id)
        if device is None or device.user_id != user_id:
            raise MessagingError("You can only modify your own messages.")

    async def mark_receipt(
        self, *, user_id: uuid.UUID, message_id: uuid.UUID, status: str
    ) -> MessageReceipt:
        message = await self._messages.get(message_id)
        if message is None:
            raise MessagingError("Unknown message.")
        await self._require_membership(message.conversation_id, user_id)

        existing = await self._message_receipts.get_for_message_and_user(
            message_id, user_id, status
        )
        if existing is not None:
            return existing

        receipt = await self._message_receipts.add(
            MessageReceipt(
                message_id=message_id, user_id=user_id, status=status, at=datetime.now(UTC)
            )
        )
        await self._notify_conversation(
            message.conversation_id,
            {"type": f"message.{status}", "message_id": str(message_id), "user_id": str(user_id)},
        )
        return receipt

    async def notify_typing(
        self, *, user_id: uuid.UUID, device_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> None:
        await self._require_membership(conversation_id, user_id)
        await self._notify_conversation(
            conversation_id,
            {"type": "typing", "user_id": str(user_id)},
            exclude_device_id=device_id,
        )

    # --- per-member conversation flags: pin, mute, archive ---

    async def set_muted(
        self, *, user_id: uuid.UUID, conversation_id: uuid.UUID, muted_until: datetime | None
    ) -> ConversationMember:
        membership = await self._require_membership(conversation_id, user_id)
        membership.muted_until = muted_until
        return membership

    async def set_archived(
        self, *, user_id: uuid.UUID, conversation_id: uuid.UUID, archived: bool
    ) -> ConversationMember:
        membership = await self._require_membership(conversation_id, user_id)
        membership.archived_at = datetime.now(UTC) if archived else None
        return membership

    async def set_pinned(
        self, *, user_id: uuid.UUID, conversation_id: uuid.UUID, pinned: bool
    ) -> ConversationMember:
        membership = await self._require_membership(conversation_id, user_id)
        membership.pinned_at = datetime.now(UTC) if pinned else None
        return membership

    async def set_disappearing_timer(
        self, *, user_id: uuid.UUID, conversation_id: uuid.UUID, seconds: int | None
    ) -> Conversation:
        await self._require_membership(conversation_id, user_id)
        conversation = await self._conversations.get(conversation_id)
        assert conversation is not None
        conversation.disappearing_timer_seconds = seconds
        return conversation

    # --- groups: Sender Keys distribution (relay only, never decrypted) ---

    async def upload_sender_key(
        self,
        *,
        device: Device,
        conversation_id: uuid.UUID,
        recipient_device_id: uuid.UUID,
        distribution_message_ref: bytes,
    ) -> SenderKey:
        await self._require_membership(conversation_id, device.user_id)
        existing = await self._sender_keys.get_for_conversation_device_and_recipient(
            conversation_id, device.id, recipient_device_id
        )
        if existing is not None:
            existing.distribution_message_ref = distribution_message_ref
            return existing
        return await self._sender_keys.add(
            SenderKey(
                conversation_id=conversation_id,
                device_id=device.id,
                recipient_device_id=recipient_device_id,
                distribution_message_ref=distribution_message_ref,
            )
        )

    async def list_sender_keys(
        self, *, user_id: uuid.UUID, conversation_id: uuid.UUID, recipient_device_id: uuid.UUID
    ) -> list[SenderKey]:
        await self._require_membership(conversation_id, user_id)
        return await self._sender_keys.list_for_conversation_and_recipient(
            conversation_id, recipient_device_id
        )

    # --- media: client-side encrypted, backend only issues signed URLs ---

    async def request_media_upload(
        self, *, user_id: uuid.UUID, content_hash: str, encrypted_size_bytes: int, content_type: str
    ) -> tuple[MediaObject, str]:
        if encrypted_size_bytes > MAX_MEDIA_SIZE_BYTES:
            raise MessagingError("File is too large.")
        key = f"media/{user_id}/{uuid.uuid4()}"
        media_object = await self._media_objects.add(
            MediaObject(
                s3_key=key,
                encrypted_size_bytes=encrypted_size_bytes,
                content_hash=content_hash,
            )
        )
        upload_url = await self._storage.create_upload_url(key=key, content_type=content_type)
        return media_object, upload_url

    async def get_media_download_url(
        self, *, user_id: uuid.UUID, media_object_id: uuid.UUID
    ) -> str:
        media_object = await self._media_objects.get(media_object_id)
        if media_object is None:
            raise MessagingError("Unknown media object.")
        if media_object.message_id is not None:
            message = await self._messages.get(media_object.message_id)
            if message is not None:
                await self._require_membership(message.conversation_id, user_id)
        return await self._storage.create_download_url(key=media_object.s3_key)

    # Block mutation (block_user/unblock_user) lives in CircleService — §24
    # is a Circle-level action with its own side effects; this service only
    # reads BlockRepository to enforce the messaging-capability effect above.

    # --- retention: disappearing messages (§21, §34.2) ---

    async def purge_expired_messages(self) -> int:
        """Called by a scheduled task (Phase 8 wires the actual scheduler —
        see tasks/README.md); the sweep logic itself lives here since it's
        messaging domain logic, not infrastructure. Tombstones rather than
        hard-deletes, matching delete_message's own behavior."""
        expired = await self._messages.list_expired(now=datetime.now(UTC))
        for message in expired:
            message.deleted_at = datetime.now(UTC)
            message.ciphertext = b""
        return len(expired)

    # --- helpers ---

    async def _notify_conversation(
        self,
        conversation_id: uuid.UUID,
        payload: dict[str, Any],
        *,
        exclude_device_id: uuid.UUID | None = None,
    ) -> None:
        members = await self._conversation_members.list_for_conversation(conversation_id)
        device_ids: list[uuid.UUID] = []
        for member in members:
            for device in await self._devices.list_for_user(member.user_id):
                if device.revoked_at is None and device.id != exclude_device_id:
                    device_ids.append(device.id)
        await self._connections.send_to_devices(
            device_ids, {**payload, "conversation_id": str(conversation_id)}
        )
