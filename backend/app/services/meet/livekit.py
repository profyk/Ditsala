"""
Real LiveKit adapter — docs/DITSALA_MEET_SPEC.md §5, §7. See
`domain/meetings/interfaces.py`'s docstring for why there's no separate
sandbox variant.
"""

from datetime import timedelta

from livekit import api as livekit_api
from livekit.protocol import egress as egress_proto

from app.core.config import Settings
from app.domain.meetings.interfaces import RecordingHandle, RoomAccessToken, RoomProvider

# LiveKit's own EgressStatus enum (protobuf int) mapped down to the three
# statuses `MeetingRecording.RECORDING_STATUSES` actually models — the
# in-between states (STARTING/ACTIVE/ENDING) only ever appear mid-flight,
# never in a `stop_egress` response, which always blocks to a terminal one.
_EGRESS_STATUS_MAP = {
    egress_proto.EgressStatus.EGRESS_STARTING: "processing",
    egress_proto.EgressStatus.EGRESS_ACTIVE: "processing",
    egress_proto.EgressStatus.EGRESS_ENDING: "processing",
    egress_proto.EgressStatus.EGRESS_COMPLETE: "ready",
    egress_proto.EgressStatus.EGRESS_FAILED: "failed",
    egress_proto.EgressStatus.EGRESS_ABORTED: "failed",
    egress_proto.EgressStatus.EGRESS_LIMIT_REACHED: "ready",
}
_NANOS_PER_SECOND = 1_000_000_000

# LiveKit tokens are short-lived by design (§5) — long enough for one
# meeting sitting, not a durable credential. A disconnect/reconnect within
# this window re-uses the same token; past it, the client re-joins via
# `POST /meetings/{id}/join` for a fresh one.
TOKEN_TTL = timedelta(hours=6)


class LiveKitRoomProvider(RoomProvider):
    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        livekit_url: str,
        s3_bucket: str = "",
        s3_region: str = "",
        s3_access_key_id: str = "",
        s3_secret_access_key: str = "",
        s3_endpoint_url: str = "",
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._livekit_url = livekit_url
        self._s3_bucket = s3_bucket
        self._s3_region = s3_region
        self._s3_access_key_id = s3_access_key_id
        self._s3_secret_access_key = s3_secret_access_key
        self._s3_endpoint_url = s3_endpoint_url

    @classmethod
    def from_settings(cls, settings: Settings) -> "LiveKitRoomProvider":
        return cls(
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
            livekit_url=settings.livekit_url,
            s3_bucket=settings.s3_bucket,
            s3_region=settings.s3_region,
            s3_access_key_id=settings.s3_access_key_id,
            s3_secret_access_key=settings.s3_secret_access_key,
            s3_endpoint_url=settings.s3_endpoint_url,
        )

    def _client(self) -> livekit_api.LiveKitAPI:
        # A fresh short-lived client per call rather than a long-held one —
        # this adapter is constructed per-request (like every other
        # provider in this codebase), so there's no good place to `aclose`
        # a persistent client anyway.
        return livekit_api.LiveKitAPI(
            self._livekit_url.replace("wss://", "https://").replace("ws://", "http://"),
            self._api_key,
            self._api_secret,
        )

    def create_access_token(
        self,
        *,
        room_name: str,
        participant_identity: str,
        participant_name: str,
        is_host: bool,
        can_publish: bool = True,
    ) -> RoomAccessToken:
        grants = livekit_api.VideoGrants(
            room_join=True,
            room=room_name,
            room_admin=is_host,
            can_publish=can_publish,
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

    async def remove_participant(self, *, room_name: str, participant_identity: str) -> None:
        async with self._client() as client:
            await client.room.remove_participant(
                livekit_api.RoomParticipantIdentity(room=room_name, identity=participant_identity)
            )

    async def set_participant_can_publish(
        self, *, room_name: str, participant_identity: str, can_publish: bool
    ) -> None:
        async with self._client() as client:
            await client.room.update_participant(
                livekit_api.UpdateParticipantRequest(
                    room=room_name,
                    identity=participant_identity,
                    permission=livekit_api.ParticipantPermission(
                        can_publish=can_publish, can_subscribe=True, can_publish_data=True
                    ),
                )
            )

    async def broadcast_data(self, *, room_name: str, payload: bytes, topic: str) -> None:
        async with self._client() as client:
            await client.room.send_data(
                livekit_api.SendDataRequest(room=room_name, data=payload, topic=topic)
            )

    async def start_recording(self, *, room_name: str, s3_key: str) -> RecordingHandle:
        async with self._client() as client:
            info = await client.egress.start_room_composite_egress(
                livekit_api.RoomCompositeEgressRequest(
                    room_name=room_name,
                    file_outputs=[
                        livekit_api.EncodedFileOutput(
                            filepath=s3_key,
                            s3=livekit_api.S3Upload(
                                access_key=self._s3_access_key_id,
                                secret=self._s3_secret_access_key,
                                region=self._s3_region,
                                endpoint=self._s3_endpoint_url or None,
                                bucket=self._s3_bucket,
                                force_path_style=bool(self._s3_endpoint_url),
                            ),
                        )
                    ],
                )
            )
        return RecordingHandle(egress_id=info.egress_id, status="processing")

    async def stop_recording(self, *, egress_id: str) -> RecordingHandle:
        async with self._client() as client:
            info = await client.egress.stop_egress(
                livekit_api.StopEgressRequest(egress_id=egress_id)
            )
        duration_seconds = None
        if info.file_results:
            duration_seconds = info.file_results[0].duration // _NANOS_PER_SECOND
        return RecordingHandle(
            egress_id=info.egress_id,
            status=_EGRESS_STATUS_MAP.get(info.status, "failed"),
            duration_seconds=duration_seconds,
        )
