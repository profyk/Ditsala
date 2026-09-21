"""
Ditsala VIP Multilingual Chat — docs/DITSALA_VIP_SPEC.md item 1/4/9.
Deliberately reuses `Conversation`/`ConversationMember` for membership
(same idempotent find-or-create shape `MessagingService.start_direct_conversation`
already has) but writes message content to `vip_messages`, never
`messages` — see `app/models/messaging.py`'s `Conversation.type` docstring
for why. v1 is 1:1 only (`conversation_type="vip_multilingual"`); group
VIP chat is a documented FUTURE cut, not an oversight.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app.domain.translation.service import TranslationService
from app.models.accounts import User
from app.models.messaging import Conversation, ConversationMember
from app.models.translation import VipMessage, VipMessageTranslation
from app.repositories.circle import BlockRepository, ContactRepository
from app.repositories.conversations import ConversationMemberRepository, ConversationRepository
from app.repositories.devices import DeviceRepository
from app.repositories.translation import (
    UserLanguagePreferenceRepository,
    VipMessageRepository,
    VipMessageTranslationRepository,
)
from app.repositories.users import UserRepository
from app.services.realtime.websocket_manager import ConnectionManager

VIP_CONVERSATION_TYPE = "vip_multilingual"


class VipChatError(Exception):
    pass


@dataclass(frozen=True)
class VipMessageWithTranslation:
    message: VipMessage
    translation: VipMessageTranslation | None


class VipChatService:
    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        conversation_members: ConversationMemberRepository,
        vip_messages: VipMessageRepository,
        vip_message_translations: VipMessageTranslationRepository,
        users: UserRepository,
        contacts: ContactRepository,
        blocks: BlockRepository,
        language_preferences: UserLanguagePreferenceRepository,
        devices: DeviceRepository,
        translation_service: TranslationService,
        connection_manager: ConnectionManager,
    ) -> None:
        self._conversations = conversations
        self._conversation_members = conversation_members
        self._vip_messages = vip_messages
        self._vip_message_translations = vip_message_translations
        self._users = users
        self._contacts = contacts
        self._blocks = blocks
        self._preferences = language_preferences
        self._devices = devices
        self._translation = translation_service
        self._connections = connection_manager

    async def start_conversation(
        self, current_user: User, other_user_id: uuid.UUID
    ) -> Conversation:
        if current_user.id == other_user_id:
            raise VipChatError("Cannot start a conversation with yourself.")
        self._translation.require_vip(current_user)
        other = await self._users.get(other_user_id)
        if other is None:
            raise VipChatError("No such user.")
        if other.account_tier != "vip":
            raise VipChatError("VIP Multilingual Chat requires both people to have Ditsala VIP.")
        if await self._blocks.exists(other_user_id, current_user.id) or await self._blocks.exists(
            current_user.id, other_user_id
        ):
            raise VipChatError("Cannot message a blocked contact.")

        existing_id = await self._conversation_members.find_conversation_id(
            current_user.id, other_user_id, conversation_type=VIP_CONVERSATION_TYPE
        )
        if existing_id is not None:
            existing = await self._conversations.get(existing_id)
            assert existing is not None
            return existing

        contact = await self._contacts.get_by_pair(current_user.id, other_user_id)
        if contact is None or contact.tier not in ("verified", "trusted"):
            raise VipChatError(
                "VIP Multilingual Chat requires an accepted Circle contact request first."
            )

        conversation = await self._conversations.add(
            Conversation(type=VIP_CONVERSATION_TYPE, created_by=current_user.id)
        )
        now = datetime.now(UTC)
        for uid in (current_user.id, other_user_id):
            await self._conversation_members.add(
                ConversationMember(conversation_id=conversation.id, user_id=uid, joined_at=now)
            )
        return conversation

    async def list_conversations(self, user_id: uuid.UUID) -> list[Conversation]:
        memberships = await self._conversation_members.list_for_user(user_id)
        conversations = []
        for membership in memberships:
            conversation = await self._conversations.get(membership.conversation_id)
            if conversation is not None and conversation.type == VIP_CONVERSATION_TYPE:
                conversations.append(conversation)
        return conversations

    async def _require_membership(
        self, conversation_id: uuid.UUID, user_id: uuid.UUID
    ) -> ConversationMember:
        membership = await self._conversation_members.get_membership(conversation_id, user_id)
        if membership is None:
            raise VipChatError("Not a member of this conversation.")
        return membership

    async def _other_member_id(self, conversation_id: uuid.UUID, user_id: uuid.UUID) -> uuid.UUID:
        members = await self._conversation_members.list_for_conversation(conversation_id)
        others = [m.user_id for m in members if m.user_id != user_id]
        if not others:
            raise VipChatError("This conversation has no other participant.")
        return others[0]

    async def send_message(
        self,
        *,
        conversation_id: uuid.UUID,
        sender: User,
        text: str,
        client_message_id: str,
    ) -> VipMessageWithTranslation:
        self._translation.require_vip(sender)
        await self._require_membership(conversation_id, sender.id)

        existing = await self._vip_messages.get_by_client_message_id(client_message_id)
        if existing is not None:
            translations = await self._vip_message_translations.list_for_message(existing.id)
            return VipMessageWithTranslation(
                message=existing, translation=translations[0] if translations else None
            )

        other_user_id = await self._other_member_id(conversation_id, sender.id)
        recipient_prefs = await self._preferences.get(other_user_id)
        if recipient_prefs is None:
            raise VipChatError(
                "The other person hasn't set a preferred language yet — ask them to open "
                "Language Settings first."
            )
        sender_prefs = await self._preferences.get(sender.id)
        source_language = (
            None
            if sender_prefs is not None and sender_prefs.auto_detect_language
            else (sender_prefs.preferred_language if sender_prefs is not None else None)
        )

        message = await self._vip_messages.add(
            VipMessage(
                conversation_id=conversation_id,
                sender_user_id=sender.id,
                client_message_id=client_message_id,
                original_text=text,
                original_language=source_language or "und",
            )
        )

        request = await self._translation.translate_and_record(
            requested_by_user_id=sender.id,
            context_type="vip_message",
            context_id=message.id,
            source_text=text,
            source_language=source_language,
            target_language=recipient_prefs.preferred_language,
        )
        if source_language is None and request.source_language:
            message.original_language = request.source_language

        translation = await self._vip_message_translations.add(
            VipMessageTranslation(
                vip_message_id=message.id,
                target_language=recipient_prefs.preferred_language,
                translated_text=request.translated_text,
                provider=request.provider,
                status=request.status,
                error_message=request.error_message,
                completed_at=request.completed_at,
            )
        )

        await self._push_to_recipient(other_user_id, message, translation)
        return VipMessageWithTranslation(message=message, translation=translation)

    async def _push_to_recipient(
        self, recipient_id: uuid.UUID, message: VipMessage, translation: VipMessageTranslation
    ) -> None:
        devices = await self._devices.list_for_user(recipient_id)
        if not devices:
            return
        await self._connections.send_to_devices(
            [d.id for d in devices],
            {
                "type": "vip_message.created",
                "conversation_id": str(message.conversation_id),
                "message_id": str(message.id),
                "sender_user_id": str(message.sender_user_id),
                "original_text": message.original_text,
                "original_language": message.original_language,
                "translated_text": translation.translated_text,
                "target_language": translation.target_language,
                "translation_status": translation.status,
                "created_at": message.created_at.isoformat(),
            },
        )

    async def list_messages(
        self, *, conversation_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[VipMessageWithTranslation]:
        await self._require_membership(conversation_id, user_id)
        messages = await self._vip_messages.list_for_conversation(conversation_id)
        translations = await self._vip_message_translations.list_for_messages(
            [m.id for m in messages]
        )
        by_message: dict[uuid.UUID, VipMessageTranslation] = {}
        for t in translations:
            by_message.setdefault(t.vip_message_id, t)
        return [
            VipMessageWithTranslation(message=m, translation=by_message.get(m.id))
            for m in messages
        ]

    async def retry_translation(
        self, *, message_id: uuid.UUID, user_id: uuid.UUID
    ) -> VipMessageTranslation:
        message = await self._vip_messages.get(message_id)
        if message is None:
            raise VipChatError("No such message.")
        await self._require_membership(message.conversation_id, user_id)
        translations = await self._vip_message_translations.list_for_message(message_id)
        if not translations:
            raise VipChatError("No translation to retry.")
        translation = translations[0]

        request = await self._translation.translate_and_record(
            requested_by_user_id=user_id,
            context_type="vip_message",
            context_id=message.id,
            source_text=message.original_text,
            source_language=(
                message.original_language if message.original_language != "und" else None
            ),
            target_language=translation.target_language,
        )
        translation.translated_text = request.translated_text
        translation.provider = request.provider
        translation.status = request.status
        translation.error_message = request.error_message
        translation.completed_at = request.completed_at
        return translation
