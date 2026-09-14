import uuid

from app.models.location import LocationAccessLog, LocationPing, LocationShare
from app.repositories.base import Repository


class LocationShareRepository(Repository[LocationShare]):
    model = LocationShare

    async def list_active_for_user(self, user_id: uuid.UUID) -> list[LocationShare]:
        """Shares where the user is either party — enforcement of the
        `trusted`-tier-only rule (§25) belongs to the domain layer, not here."""
        result = await self.session.execute(
            self._select().where(
                LocationShare.revoked_at.is_(None),
                (LocationShare.sharer_user_id == user_id)
                | (LocationShare.recipient_user_id == user_id),
            )
        )
        return list(result.scalars().all())


class LocationPingRepository(Repository[LocationPing]):
    model = LocationPing

    async def list_for_share(self, location_share_id: uuid.UUID) -> list[LocationPing]:
        result = await self.session.execute(
            self._select().where(LocationPing.location_share_id == location_share_id)
        )
        return list(result.scalars().all())


class LocationAccessLogRepository(Repository[LocationAccessLog]):
    model = LocationAccessLog
