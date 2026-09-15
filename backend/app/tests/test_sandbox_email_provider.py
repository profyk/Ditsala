"""
Proves SandboxEmailProvider genuinely sends over SMTP to a local catcher
(Mailpit) rather than being a hand-rolled no-op — docs/DITSALA_MASTER_SPEC.md
§3.4: sandbox adapters must exercise the real protocol/provider, not fake it.

Requires Mailpit (or any Mailpit-API-compatible catcher) running locally —
see infra/docker-compose.yml. Skips if it isn't reachable, since this
environment ran it as a standalone binary rather than via Docker (no Docker
available here — see CLAUDE.md).
"""

import uuid

import httpx
import pytest

from app.core.config import get_settings
from app.services.email.sandbox import SandboxEmailProvider

MAILPIT_API = "http://127.0.0.1:8025/api/v1"


def _mailpit_available() -> bool:
    try:
        httpx.get(f"{MAILPIT_API}/info", timeout=1.0).raise_for_status()
        return True
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not _mailpit_available(), reason="Mailpit not reachable locally")


async def test_sandbox_email_provider_delivers_to_mailpit():
    provider = SandboxEmailProvider(get_settings())
    to_email = f"{uuid.uuid4()}@test.local"
    code = "123456"

    await provider.send_verification_code(to_email=to_email, code=code)

    search = httpx.get(f"{MAILPIT_API}/search", params={"query": f"to:{to_email}"}, timeout=5.0)
    search.raise_for_status()
    messages = search.json()["messages"]
    assert len(messages) == 1

    message_id = messages[0]["ID"]
    detail = httpx.get(f"{MAILPIT_API}/message/{message_id}", timeout=5.0)
    detail.raise_for_status()
    body = detail.json()
    assert code in body["Text"]
    assert body["Subject"] == "Your DITSALA verification code"
