import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import CursorResult, delete, or_, select

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

    async def purge_expired(self, *, grace_hours: int = 24) -> int:
        """
        §34.2: pings outlive their share's `expires_at`/`revoked_at` by
        only `grace_hours` (covers the `location_access_log` transparency
        use case), then are hard-deleted. The spec's "90 days if
        SOS-linked" exception is not implemented — no FK currently ties a
        `location_pings` row to an `sos_events` record (§26 stores only a
        loose `last_known_location_ref` string at trigger time, not a
        share reference) — see docs/SECURITY_GAPS.md.
        """
        cutoff = datetime.now(UTC) - timedelta(hours=grace_hours)
        expired_share_ids = select(LocationShare.id).where(
            or_(LocationShare.revoked_at < cutoff, LocationShare.expires_at < cutoff)
        )
        result = await self.session.execute(
            delete(LocationPing).where(LocationPing.location_share_id.in_(expired_share_ids))
        )
        assert isinstance(result, CursorResult)
        return result.rowcount


class LocationAccessLogRepository(Repository[LocationAccessLog]):
    model = LocationAccessLog

    async def list_for_share(self, location_share_id: uuid.UUID) -> list[LocationAccessLog]:
        result = await self.session.execute(
            self._select().where(LocationAccessLog.location_share_id == location_share_id)
        )
        return list(result.scalars().all())
