"""
§34.4's data-export bundle for a completed "access" request — see
`docs/SECURITY_GAPS.md`'s "Data export bundle's deeper joins are hand-
picked, not a generic multi-hop walker" entry for this implementation's
disclosed scope boundary.

Reflection-driven rather than a hand-maintained table list: it walks
every mapped model looking for a foreign key to `users.id` and pulls
whatever rows reference the requesting user, so a new table added later
is picked up automatically instead of silently missing from someone's
export (the exact failure mode a hand-enumerated list of 30+ tables
invites). Every column is filtered through the same §5 classification
registry the rest of the codebase already treats as the source of truth:
P0 (cryptographic secrets — key hashes, refresh-token hashes) is never
included, P2 (message ciphertext, precise location) is replaced with a
placeholder rather than the raw value — same "no admin path, ever" spirit
as §7, applied here to the export pipeline rather than an admin screen —
while the surrounding row (timestamps, conversation/contact ids, etc.)
still appears, so the bundle reflects *that* something happened without
leaking content a human was never meant to read off a server. P1 (KYC
result summaries) and P3 (everything else) pass through unredacted.

**Scope boundary, disclosed rather than silent**: the generic scan above
only reaches tables with a *direct* foreign key to `users.id` — it does
not walk multi-hop relationships on its own. Three specific deeper cases
are worth the user's own data and get a deliberate, hand-written join
each, rather than a generalized (and riskier — see below) multi-hop
walker: `messages` (sender is one hop away via
`sender_device_id -> devices.user_id`; explicitly promised by this
feature's own tracked gap as "metadata, never content"), `media_objects`
(one hop further, via `message_id -> messages`), and `location_pings`
(one hop via `location_share_id -> location_shares.sharer_user_id` — only
the *sharer's* own pings, not a recipient's, since a ping is the sharer's
GPS reading, not the recipient's data). Still out of scope: tables
reachable only through a relationship that isn't cleanly "this user's own
data" (e.g. `meeting_participants` rows for meetings the user merely
attended, not hosted) — a generic walker would silently traverse those
too, which is exactly the risk this hand-picked approach avoids.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.classification import DataClass, classify
from app.domain.messaging.interfaces import StorageProvider
from app.models.accounts import User
from app.models.base import Base
from app.models.devices import Device
from app.models.location import LocationPing, LocationShare
from app.models.messaging import MediaObject, Message

_REDACTED = "[not included in export: P2 content/location — server-opaque or precise-location data]"

_USERS_TABLE = "users"


def _serialize_row(table_name: str, row: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column in row.__table__.columns:
        data_class = classify(table_name, column.name)
        if data_class is DataClass.P0_CRYPTOGRAPHIC_SECRET:
            continue
        if data_class is DataClass.P2_MESSAGE_CONTENT_LOCATION:
            result[column.name] = _REDACTED
            continue
        result[column.name] = getattr(row, column.name)
    return result


class DataExportService:
    def __init__(self, *, session: AsyncSession, storage: StorageProvider) -> None:
        self._session = session
        self._storage = storage

    async def generate_export(self, user: User) -> str:
        """Builds the bundle and uploads it, returning the storage key (not
        a URL — a fresh presigned download URL is minted per download
        request, since these expire)."""
        tables: dict[str, list[dict[str, Any]]] = {
            _USERS_TABLE: [_serialize_row(_USERS_TABLE, user)]
        }

        for mapper in Base.registry.mappers:
            table = mapper.local_table
            if not isinstance(table, Table) or table.name == _USERS_TABLE:
                continue
            user_columns = [
                column
                for column in table.columns
                if any(fk.target_fullname == "users.id" for fk in column.foreign_keys)
            ]
            if not user_columns:
                continue

            rows: list[dict[str, Any]] = []
            seen_pks: set[tuple[Any, ...]] = set()
            for column in user_columns:
                result = await self._session.execute(select(mapper.class_).where(column == user.id))
                for obj in result.scalars().all():
                    pk = tuple(getattr(obj, pk_col.name) for pk_col in table.primary_key.columns)
                    if pk in seen_pks:
                        continue
                    seen_pks.add(pk)
                    rows.append(_serialize_row(table.name, obj))

            if rows:
                tables[table.name] = rows

        device_ids = await self._own_device_ids(user)
        message_rows, message_ids = await self._export_own_messages(device_ids)
        if message_rows:
            tables["messages"] = message_rows

        media_rows = await self._export_own_media_objects(message_ids)
        if media_rows:
            tables["media_objects"] = media_rows

        location_ping_rows = await self._export_own_location_pings(user)
        if location_ping_rows:
            tables["location_pings"] = location_ping_rows

        payload = json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "user_id": str(user.id),
                "tables": tables,
            },
            default=str,
            indent=2,
        ).encode("utf-8")

        key = f"data-exports/{user.id}/{uuid.uuid4()}.json"
        await self._storage.put_object(key=key, data=payload, content_type="application/json")
        return key

    async def create_download_url(self, key: str) -> str:
        return await self._storage.create_download_url(key=key)

    async def _own_device_ids(self, user: User) -> list[uuid.UUID]:
        result = await self._session.execute(select(Device.id).where(Device.user_id == user.id))
        return list(result.scalars().all())

    async def _export_own_messages(
        self, device_ids: list[uuid.UUID]
    ) -> tuple[list[dict[str, Any]], list[uuid.UUID]]:
        """See the module docstring's "scope boundary" note — `messages`
        has no direct `users.id` column, so it's not reached by the
        generic scan above. Returns the message ids alongside the
        serialized rows so `_export_own_media_objects` can join off them
        without re-deriving device ownership."""
        if not device_ids:
            return [], []
        result = await self._session.execute(
            select(Message).where(Message.sender_device_id.in_(device_ids))
        )
        messages = list(result.scalars().all())
        rows = [_serialize_row("messages", obj) for obj in messages]
        return rows, [m.id for m in messages]

    async def _export_own_media_objects(self, message_ids: list[uuid.UUID]) -> list[dict[str, Any]]:
        """One hop further than `messages` itself — media attached to a
        message this user sent."""
        if not message_ids:
            return []
        result = await self._session.execute(
            select(MediaObject).where(MediaObject.message_id.in_(message_ids))
        )
        return [_serialize_row("media_objects", obj) for obj in result.scalars().all()]

    async def _export_own_location_pings(self, user: User) -> list[dict[str, Any]]:
        """Only the pings recorded under a share *this user created* —
        `location_pings` has no direct `users.id` column, and a
        recipient's own view of someone else's pings isn't this user's
        own data to export."""
        share_ids_result = await self._session.execute(
            select(LocationShare.id).where(LocationShare.sharer_user_id == user.id)
        )
        share_ids = list(share_ids_result.scalars().all())
        if not share_ids:
            return []
        result = await self._session.execute(
            select(LocationPing).where(LocationPing.location_share_id.in_(share_ids))
        )
        return [_serialize_row("location_pings", obj) for obj in result.scalars().all()]
