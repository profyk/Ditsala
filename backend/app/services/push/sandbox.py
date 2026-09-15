from dataclasses import dataclass
from typing import Any

import structlog

from app.domain.notifications.interfaces import PushProvider

logger = structlog.get_logger()


@dataclass(frozen=True)
class SentPush:
    push_token: str
    title: str
    body: str
    data: dict[str, Any]


class SandboxPushProvider(PushProvider):
    """
    Documented exception to the "sandbox adapter calls the real provider's
    own test/sandbox mode" pattern (docs/DITSALA_MASTER_SPEC.md §3.4,
    Working Rule 4): unlike Twilio/Smile ID, Expo's push API has no
    distinct sandbox environment — a real request to a fake token just
    fails, there's no equivalent of a documented "magic" test value. This
    records sends in memory instead of touching the network, and is
    explicitly logged as a gap here per Working Rule 6 rather than shipped
    silently. See docs/SECURITY_GAPS.md.
    """

    def __init__(self) -> None:
        self.sent: list[SentPush] = []

    async def send_push(
        self, *, push_token: str, title: str, body: str, data: dict[str, Any] | None = None
    ) -> None:
        self.sent.append(SentPush(push_token=push_token, title=title, body=body, data=data or {}))
        # Title only — body/data may carry SOS/location context (§5), and
        # the allowlist-logging policy (core/logging.py) means we log the
        # minimum needed to confirm a send happened in dev, not its content.
        logger.info("sandbox_push_send", push_token_suffix=push_token[-6:], title=title)
