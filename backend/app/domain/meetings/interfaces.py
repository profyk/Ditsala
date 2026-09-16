"""
Ditsala Meet — docs/DITSALA_MEET_SPEC.md §2, §5. LiveKit is the SFU;
this Protocol is the one seam between MeetingService and LiveKit's own
SDK, following the same real-adapter-behind-an-interface pattern every
other external dependency in this codebase uses (Working Rule 4).

No `Sandbox*` adapter exists here, unlike KYC/OTP/email — deliberately.
Minting a LiveKit access token is a pure local JWT-signing operation (no
network call to LiveKit is involved), so the real `LiveKitRoomProvider`
can be exercised for real in tests just by giving it throwaway
key/secret strings — there's no meaningfully different "sandbox"
behavior to build. See `app/tests/test_meeting_service.py`.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RoomAccessToken:
    token: str
    livekit_url: str


class RoomProvider(Protocol):
    def create_access_token(
        self,
        *,
        room_name: str,
        participant_identity: str,
        participant_name: str,
        is_host: bool,
    ) -> RoomAccessToken:
        """
        Mints a short-lived, room-and-identity-scoped access token for one
        participant. Never exposes the underlying API key/secret to any
        caller beyond this process — the client only ever receives the
        signed token (§5, §25/§53: no vendor secret in client code).
        """
        ...
