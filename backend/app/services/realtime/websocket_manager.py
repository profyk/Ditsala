"""
In-process connection registry for the authenticated realtime transport
(docs/DITSALA_MASTER_SPEC.md §18-21: "WebSocket transport"). Deliberately
in-memory, single-process — Redis pub/sub is the documented evolution path
once this needs to fan out across multiple backend instances (§3: Redis
is locked in for "cache/realtime/queues"), but a single process is all
this phase's scope needs, and adding Redis here now would be solving a
problem that doesn't exist yet.
"""

import uuid
from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, set[WebSocket]] = defaultdict(set)

    async def connect(self, device_id: uuid.UUID, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[device_id].add(websocket)

    def disconnect(self, device_id: uuid.UUID, websocket: WebSocket) -> None:
        self._connections[device_id].discard(websocket)
        if not self._connections[device_id]:
            del self._connections[device_id]

    async def send_to_device(self, device_id: uuid.UUID, payload: dict[str, Any]) -> None:
        for websocket in list(self._connections.get(device_id, ())):
            await websocket.send_json(payload)

    async def send_to_devices(self, device_ids: list[uuid.UUID], payload: dict[str, Any]) -> None:
        for device_id in device_ids:
            await self.send_to_device(device_id, payload)


# One instance per process — connections are inherently process-local.
connection_manager = ConnectionManager()
