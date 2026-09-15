"""
Location sharing — docs/DITSALA_MASTER_SPEC.md §25. Off by default;
sharing requires an explicit, time-bounded grant to a `trusted`-tier
contact only, never `verified`/`unverified`. Framework-agnostic per §3.3.
"""

import uuid
from datetime import UTC, datetime, timedelta

from app.models.location import LocationAccessLog, LocationPing, LocationShare
from app.repositories.circle import ContactRepository
from app.repositories.location import (
    LocationAccessLogRepository,
    LocationPingRepository,
    LocationShareRepository,
)


class LocationError(Exception):
    """Raised for location preconditions a caller should turn into a 4xx, not a 500."""


class LocationService:
    def __init__(
        self,
        *,
        shares: LocationShareRepository,
        pings: LocationPingRepository,
        access_log: LocationAccessLogRepository,
        contacts: ContactRepository,
    ) -> None:
        self._shares = shares
        self._pings = pings
        self._access_log = access_log
        self._contacts = contacts

    async def create_share(
        self, *, sharer_id: uuid.UUID, recipient_id: uuid.UUID, duration_seconds: int
    ) -> LocationShare:
        contact = await self._contacts.get_by_pair(sharer_id, recipient_id)
        if contact is None or contact.tier != "trusted":
            raise LocationError("Location can only be shared with a trusted Circle contact.")
        now = datetime.now(UTC)
        return await self._shares.add(
            LocationShare(
                sharer_user_id=sharer_id,
                recipient_user_id=recipient_id,
                starts_at=now,
                expires_at=now + timedelta(seconds=duration_seconds),
            )
        )

    async def revoke_share(self, *, user_id: uuid.UUID, share_id: uuid.UUID) -> LocationShare:
        share = await self._shares.get(share_id)
        if share is None or share.sharer_user_id != user_id:
            raise LocationError("No such location share.")
        share.revoked_at = datetime.now(UTC)
        return share

    def _is_active(self, share: LocationShare) -> bool:
        return share.revoked_at is None and share.expires_at > datetime.now(UTC)

    async def list_shares_by_me(self, user_id: uuid.UUID) -> list[LocationShare]:
        shares = await self._shares.list_active_for_user(user_id)
        return [s for s in shares if s.sharer_user_id == user_id]

    async def list_shares_to_me(self, user_id: uuid.UUID) -> list[LocationShare]:
        shares = await self._shares.list_active_for_user(user_id)
        return [s for s in shares if s.recipient_user_id == user_id]

    async def record_ping(
        self,
        *,
        sharer_id: uuid.UUID,
        share_id: uuid.UUID,
        lat: float,
        lng: float,
        accuracy_m: float,
    ) -> LocationPing:
        share = await self._shares.get(share_id)
        if share is None or share.sharer_user_id != sharer_id:
            raise LocationError("No such location share.")
        if not self._is_active(share):
            raise LocationError("This location share is no longer active.")
        return await self._pings.add(
            LocationPing(
                location_share_id=share_id,
                lat=lat,
                lng=lng,
                accuracy_m=accuracy_m,
                recorded_at=datetime.now(UTC),
            )
        )

    async def list_pings(
        self, *, viewer_id: uuid.UUID, share_id: uuid.UUID
    ) -> list[LocationPing]:
        share = await self._shares.get(share_id)
        if share is None or viewer_id not in (share.sharer_user_id, share.recipient_user_id):
            raise LocationError("No such location share.")
        if viewer_id == share.recipient_user_id:
            # §25 access transparency: every view is logged and surfaced
            # back to the sharer — no silent surveillance within a grant.
            await self._access_log.add(
                LocationAccessLog(
                    location_share_id=share_id,
                    accessed_by_user_id=viewer_id,
                    accessed_at=datetime.now(UTC),
                )
            )
        return await self._pings.list_for_share(share_id)

    async def list_access_log(
        self, *, sharer_id: uuid.UUID, share_id: uuid.UUID
    ) -> list[LocationAccessLog]:
        share = await self._shares.get(share_id)
        if share is None or share.sharer_user_id != sharer_id:
            raise LocationError("No such location share.")
        return await self._access_log.list_for_share(share_id)
