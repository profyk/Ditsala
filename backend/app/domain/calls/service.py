"""
Call signaling — docs/DITSALA_MASTER_SPEC.md §27. WebRTC media is
peer-to-peer with DTLS-SRTP end-to-end and coturn as TURN relay only
(locked decision) — the backend's role here is exactly the same shape as
messaging's (§7.3): it relays opaque SDP offer/answer/ICE-candidate
payloads over the realtime WebSocket transport and never touches media
itself, so this service is real, fully tested code regardless of whether
a native WebRTC module has been exercised on a device (see ADR 0007).
Group calls are out of v1 scope (settled) — calls are gated to `direct`
conversations, exactly two participants.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from app.models.calls import Call, CallParticipant
from app.repositories.calls import CallParticipantRepository, CallRepository
from app.repositories.conversations import ConversationMemberRepository, ConversationRepository
from app.repositories.devices import DeviceRepository
from app.services.realtime.websocket_manager import ConnectionManager


class CallError(Exception):
    """Raised for call preconditions a caller should turn into a 4xx, not a 500."""


class CallService:
    def __init__(
        self,
        *,
        calls: CallRepository,
        participants: CallParticipantRepository,
        conversations: ConversationRepository,
        conversation_members: ConversationMemberRepository,
        devices: DeviceRepository,
        connection_manager: ConnectionManager,
    ) -> None:
        self._calls = calls
        self._participants = participants
        self._conversations = conversations
        self._conversation_members = conversation_members
        self._devices = devices
        self._connections = connection_manager

    async def initiate_call(
        self, *, initiator_id: uuid.UUID, conversation_id: uuid.UUID, call_type: str
    ) -> Call:
        conversation = await self._conversations.get(conversation_id)
        if conversation is None or conversation.type != "direct":
            raise CallError("Only 1:1 calls are supported in this version.")
        membership = await self._conversation_members.get_membership(
            conversation_id, initiator_id
        )
        if membership is None:
            raise CallError("Not a member of this conversation.")

        members = await self._conversation_members.list_for_conversation(conversation_id)
        other_member = next((m for m in members if m.user_id != initiator_id), None)
        if other_member is None:
            raise CallError("No other participant in this conversation.")

        call = await self._calls.add(
            Call(conversation_id=conversation_id, initiator_user_id=initiator_id, type=call_type)
        )
        now = datetime.now(UTC)
        await self._participants.add(
            CallParticipant(call_id=call.id, user_id=initiator_id, joined_at=now)
        )
        await self._participants.add(
            CallParticipant(call_id=call.id, user_id=other_member.user_id)
        )

        await self._notify_user(
            other_member.user_id,
            {
                "type": "call.ringing",
                "call_id": str(call.id),
                "conversation_id": str(conversation_id),
                "call_type": call_type,
                "from_user_id": str(initiator_id),
            },
        )
        return call

    async def _require_participant(
        self, call_id: uuid.UUID, user_id: uuid.UUID
    ) -> tuple[Call, CallParticipant]:
        call = await self._calls.get(call_id)
        if call is None:
            raise CallError("No such call.")
        participants = await self._participants.list_for_call(call_id)
        mine = next((p for p in participants if p.user_id == user_id), None)
        if mine is None:
            raise CallError("Not a participant in this call.")
        return call, mine

    async def _other_participant(self, call_id: uuid.UUID, user_id: uuid.UUID) -> CallParticipant:
        participants = await self._participants.list_for_call(call_id)
        other = next((p for p in participants if p.user_id != user_id), None)
        if other is None:
            raise CallError("No other participant in this call.")
        return other

    async def answer_call(self, *, call_id: uuid.UUID, user_id: uuid.UUID) -> Call:
        call, mine = await self._require_participant(call_id, user_id)
        if call.status not in ("ringing", "active"):
            raise CallError(f"Cannot answer a call in status {call.status!r}.")
        mine.joined_at = datetime.now(UTC)
        if call.status == "ringing":
            call.status = "active"
            call.started_at = datetime.now(UTC)
        other = await self._other_participant(call_id, user_id)
        await self._notify_user(other.user_id, {"type": "call.answered", "call_id": str(call.id)})
        return call

    async def decline_call(self, *, call_id: uuid.UUID, user_id: uuid.UUID) -> Call:
        call, _mine = await self._require_participant(call_id, user_id)
        if call.status != "ringing":
            raise CallError(f"Cannot decline a call in status {call.status!r}.")
        call.status = "declined"
        call.ended_at = datetime.now(UTC)
        other = await self._other_participant(call_id, user_id)
        await self._notify_user(other.user_id, {"type": "call.declined", "call_id": str(call.id)})
        return call

    async def end_call(self, *, call_id: uuid.UUID, user_id: uuid.UUID) -> Call:
        call, mine = await self._require_participant(call_id, user_id)
        if call.status in ("ended", "declined", "missed"):
            return call
        call.status = "missed" if call.status == "ringing" else "ended"
        call.ended_at = datetime.now(UTC)
        mine.left_at = datetime.now(UTC)
        other = await self._other_participant(call_id, user_id)
        await self._notify_user(other.user_id, {"type": "call.ended", "call_id": str(call.id)})
        return call

    async def relay_signal(
        self, *, call_id: uuid.UUID, from_user_id: uuid.UUID, payload: dict[str, Any]
    ) -> None:
        """`payload` is an opaque WebRTC signaling message (SDP offer/
        answer or an ICE candidate) — this service never inspects its
        shape, exactly like message ciphertext (§7.3)."""
        call, _mine = await self._require_participant(call_id, from_user_id)
        if call.status not in ("ringing", "active"):
            return  # stale signal for an already-ended call — drop silently
        other = await self._other_participant(call_id, from_user_id)
        await self._notify_user(
            other.user_id,
            {
                "type": "call.signal",
                "call_id": str(call.id),
                "from_user_id": str(from_user_id),
                "payload": payload,
            },
        )

    async def switch_media(
        self, *, call_id: uuid.UUID, user_id: uuid.UUID, call_type: str
    ) -> Call:
        """
        §27: either side can switch a live call between voice and video at
        any time (e.g. "turn my camera on") — this is a renegotiation, not
        a new call. `call.type` becomes "the call's current mode," and the
        actual track add/remove + SDP renegotiation is just another
        `call.signal` exchange the clients drive themselves; this method
        only updates the shared state and tells the other side what
        changed, so its UI (e.g. showing a remote video view) can react
        before the renegotiated SDP even arrives.
        """
        call, _mine = await self._require_participant(call_id, user_id)
        if call.status != "active":
            raise CallError("Can only switch media on an active call.")
        if call_type == call.type:
            return call
        call.type = call_type
        other = await self._other_participant(call_id, user_id)
        await self._notify_user(
            other.user_id,
            {
                "type": "call.media_changed",
                "call_id": str(call.id),
                "call_type": call_type,
                "changed_by_user_id": str(user_id),
            },
        )
        return call

    async def list_calls(self, user_id: uuid.UUID) -> list[Call]:
        return await self._calls.list_for_user(user_id)

    async def _notify_user(self, user_id: uuid.UUID, event: dict[str, Any]) -> None:
        device_ids = [
            device.id
            for device in await self._devices.list_for_user(user_id)
            if device.revoked_at is None
        ]
        await self._connections.send_to_devices(device_ids, event)
