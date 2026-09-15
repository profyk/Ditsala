"""
Provider interfaces for push + SMS delivery (docs/DITSALA_MASTER_SPEC.md
§26, §31). Not in spec §3.4's provider table (that only lists KYC/OTP/
Email) — but Working Rule 4 ("every external provider behind an
interface with a real adapter + a Sandbox* adapter") applies generally,
same treatment `StorageProvider` (Phase 4) already got. Concrete adapters
live in app/services/{push,sms}/.
"""

from typing import Any, Protocol


class PushProvider(Protocol):
    async def send_push(
        self, *, push_token: str, title: str, body: str, data: dict[str, Any] | None = None
    ) -> None: ...


class SmsProvider(Protocol):
    async def send_sms(self, *, to_phone: str, body: str) -> None: ...
