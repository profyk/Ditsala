"""
§34.4's data-export bundle for a completed "access" request — see
`docs/SECURITY_GAPS.md`'s "Data export bundle only reaches tables one hop
from users.id" entry for this implementation's disclosed scope boundary.

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
not walk multi-hop relationships. `messages` has no such direct column
(a message's sender is identified via `sender_device_id -> devices.user_id`,
one hop removed) but is explicitly promised by this feature's own tracked
gap ("the user's own message metadata, never content"), so it gets one
deliberate, hand-written join below rather than a generalized multi-hop
walker. Tables reachable only through a *deeper* chain (e.g.
`media_objects` via `messages`, or `location_pings` via `location_shares`)
are still out of scope — see `docs/SECURITY_GAPS.md`.
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
from app.models.messaging import Message

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

        message_rows = await self._export_own_messages(user)
        if message_rows:
            tables["messages"] = message_rows

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

    async def _export_own_messages(self, user: User) -> list[dict[str, Any]]:
        """See the module docstring's "scope boundary" note — `messages`
        has no direct `users.id` column, so it's not reached by the
        generic scan above."""
        device_ids_result = await self._session.execute(
            select(Device.id).where(Device.user_id == user.id)
        )
        device_ids = list(device_ids_result.scalars().all())
        if not device_ids:
            return []
        result = await self._session.execute(
            select(Message).where(Message.sender_device_id.in_(device_ids))
        )
        return [_serialize_row("messages", obj) for obj in result.scalars().all()]
