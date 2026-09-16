"""
Real LiveKit adapter — docs/DITSALA_MEET_SPEC.md §5. See
`domain/meetings/interfaces.py`'s docstring for why there's no separate
sandbox variant: token minting never calls LiveKit's network API at all,
it's a local JWT signed with the configured key/secret.
"""

from datetime import timedelta

from livekit import api as livekit_api

from app.domain.meetings.interfaces import RoomAccessToken, RoomProvider

# LiveKit tokens are short-lived by design (§5) — long enough for one
# meeting sitting, not a durable credential. A disconnect/reconnect within
# this window re-uses the same token; past it, the client re-joins via
# `POST /meetings/{id}/join` for a fresh one.
TOKEN_TTL = timedelta(hours=6)


class LiveKitRoomProvider(RoomProvider):
    def __init__(self, *, api_key: str, api_secret: str, livekit_url: str) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._livekit_url = livekit_url

    def create_access_token(
        self,
        *,
        room_name: str,
        participant_identity: str,
        participant_name: str,
        is_host: bool,
    ) -> RoomAccessToken:
        grants = livekit_api.VideoGrants(
            room_join=True,
            room=room_name,
            room_admin=is_host,
            can_publish=True,
            can_subscribe=True,
        )
        token = (
            livekit_api.AccessToken(self._api_key, self._api_secret)
            .with_identity(participant_identity)
            .with_name(participant_name)
            .with_grants(grants)
            .with_ttl(TOKEN_TTL)
            .to_jwt()
        )
        return RoomAccessToken(token=token, livekit_url=self._livekit_url)
