import httpx

from app.core.config import Settings
from app.domain.onboarding.interfaces import EmailProvider
from app.services.email.templates import VERIFICATION_SUBJECT, verification_body


class ResendEmailProvider(EmailProvider):
    """
    Real adapter — Resend's HTTP API (docs/DITSALA_MASTER_SPEC.md §3.4).
    Requires RESEND_API_KEY; not exercised in this environment (no vendor
    account) — see CLAUDE.md "Phase 2" notes for what's code-complete vs.
    live-verified.
    """

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.resend_api_key
        self._from_address = settings.resend_from_address

    async def send_verification_code(self, *, to_email: str, code: str) -> None:
        text_body, html_body = verification_body(code)
        async with httpx.AsyncClient(base_url="https://api.resend.com", timeout=10.0) as client:
            response = await client.post(
                "/emails",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "from": self._from_address,
                    "to": [to_email],
                    "subject": VERIFICATION_SUBJECT,
                    "text": text_body,
                    "html": html_body,
                },
            )
            response.raise_for_status()
