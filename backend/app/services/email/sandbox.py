from email.message import EmailMessage

import aiosmtplib

from app.core.config import Settings
from app.domain.onboarding.interfaces import EmailProvider
from app.services.email.templates import VERIFICATION_SUBJECT, verification_body


class SandboxEmailProvider(EmailProvider):
    """
    Sends real SMTP to a local catcher (Mailpit by default — see
    infra/docker-compose.yml) rather than a hand-rolled fake: the message
    genuinely leaves the process over SMTP and can be inspected via
    Mailpit's own UI/API, which is what makes this a legitimate sandbox
    adapter rather than a stub (docs/DITSALA_MASTER_SPEC.md §3.4).
    """

    def __init__(self, settings: Settings) -> None:
        self._host = settings.sandbox_smtp_host
        self._port = settings.sandbox_smtp_port
        self._from_address = settings.sandbox_from_address

    async def send_verification_code(self, *, to_email: str, code: str) -> None:
        text_body, html_body = verification_body(code)
        message = EmailMessage()
        message["From"] = self._from_address
        message["To"] = to_email
        message["Subject"] = VERIFICATION_SUBJECT
        message.set_content(text_body)
        message.add_alternative(html_body, subtype="html")

        await aiosmtplib.send(message, hostname=self._host, port=self._port)
