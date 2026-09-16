"""
Ditsala Meet — docs/DITSALA_MEET_SPEC.md §2, §5, §7 (host controls),
§9 Phase 2. LiveKit is the SFU; this Protocol is the one seam between
MeetingService and LiveKit's own SDK, following the same real-adapter-
behind-an-interface pattern every other external dependency in this
codebase uses (Working Rule 4).

No `Sandbox*` adapter exists here, unlike KYC/OTP/email — deliberately.
Every method here is either a pure local operation (token minting: a
JWT signed locally, no network call) or a real call to LiveKit's own
server API using throwaway local credentials in tests — there's no
meaningfully different "sandbox" behavior to build, and LiveKit itself
has no separate sandbox/production API distinction the way Twilio/Smile
ID do. See `app/tests/test_meeting_service.py`.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RoomAccessToken:
    token: str
    livekit_url: str


@dataclass(frozen=True)
class RecordingHandle:
    egress_id: str
    # Mirrors `models.meetings.MeetingRecording.RECORDING_STATUSES` —
    # "processing" right after `start_recording`, or LiveKit Egress's own
    # completion status (mapped from its `EgressStatus` enum) once
    # `stop_recording` returns.
    status: str = "processing"
    duration_seconds: int | None = None


class RoomProvider(Protocol):
    def create_access_token(
        self,
        *,
        room_name: str,
        participant_identity: str,
        participant_name: str,
        is_host: bool,
        can_publish: bool = True,
    ) -> RoomAccessToken:
        """
        Mints a short-lived, room-and-identity-scoped access token for one
        participant. Never exposes the underlying API key/secret to any
        caller beyond this process — the client only ever receives the
        signed token (§5, §25/§53: no vendor secret in client code).

        `can_publish=False` (§9 Phase 4 — webinar/town_hall/conference
        audience members) denies the publish grant at token-mint time
        rather than granting then revoking after join, so a view-only
        attendee's client never even briefly holds publish rights.
        """
        ...

    async def remove_participant(self, *, room_name: str, participant_identity: str) -> None:
        """Real, server-enforced — disconnects the participant from the
        LiveKit room itself, not just a client-side UI hide."""
        ...

    async def set_participant_can_publish(
        self, *, room_name: str, participant_identity: str, can_publish: bool
    ) -> None:
        """Host mute enforcement (§7): revoking `can_publish` stops a
        participant from publishing any track (audio or video) at the
        SFU level — a client can't route around this by ignoring a
        client-side mute button, unlike a purely UI-driven mute."""
        ...

    async def broadcast_data(
        self, *, room_name: str, payload: bytes, topic: str
    ) -> None:
        """Real-time, non-media signals to every participant in a room
        (reactions, raise-hand, chat, poll updates) via LiveKit's own
        data channel — no separate WebSocket transport needed for
        Meet-internal events, unlike DITSALA's own messaging/calls."""
        ...

    async def start_recording(
        self, *, room_name: str, s3_key: str
    ) -> RecordingHandle:
        """Starts a room-composite recording (§7 Phase 2) via LiveKit
        Egress, writing directly to the same S3-compatible bucket
        `StorageProvider` already uses — DITSALA's backend never
        touches the recording bytes itself."""
        ...

    async def stop_recording(self, *, egress_id: str) -> RecordingHandle:
        """Stops the egress and returns its resulting status — LiveKit's
        `stop_egress` call blocks until the egress reports a terminal
        state, so the returned handle reflects the real outcome rather
        than an assumed success (§9 Phase 2: no egress-completion webhook
        is wired yet, so this synchronous result is the only signal)."""
        ...
