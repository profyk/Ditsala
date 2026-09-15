from typing import Any

import httpx

from app.core.config import Settings
from app.domain.notifications.interfaces import PushProvider


class ExpoPushProvider(PushProvider):
    """
    Real adapter — Expo's push notification HTTP API
    (docs/DITSALA_MASTER_SPEC.md §31: "Expo Notifications -> APNs/FCM").
    Generic payloads only (§31) — `data` is opaque, never message
    plaintext or KYC/biometric content (§5).
    """

    _ENDPOINT = "https://exp.host/--/api/v2/push/send"

    def __init__(self, *, access_token: str = "") -> None:
        self._access_token = access_token

    async def send_push(
        self, *, push_token: str, title: str, body: str, data: dict[str, Any] | None = None
    ) -> None:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                self._ENDPOINT,
                headers=headers,
                json={"to": push_token, "title": title, "body": body, "data": data or {}},
            )
            response.raise_for_status()

    @classmethod
    def from_settings(cls, settings: Settings) -> "ExpoPushProvider":
        return cls(access_token=settings.expo_push_access_token)
