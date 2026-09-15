import httpx

from app.core.config import Settings
from app.domain.notifications.interfaces import SmsProvider


class TwilioSmsProvider(SmsProvider):
    """
    Real adapter — Twilio's Programmable Messaging API (distinct from
    Twilio Verify, which only sends OTP codes — see
    `app/services/otp/twilio_verify.py`). Used for §26 SOS escalation's
    SMS fallback, so a Circle member without the app open still gets
    notified. Not exercised in this environment (no vendor account) —
    same limitation as the OTP/KYC adapters, see CLAUDE.md.
    """

    def __init__(self, *, account_sid: str, auth_token: str, from_number: str) -> None:
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._from_number = from_number

    async def send_sms(self, *, to_phone: str, body: str) -> None:
        async with httpx.AsyncClient(
            base_url=f"https://api.twilio.com/2010-04-01/Accounts/{self._account_sid}",
            auth=(self._account_sid, self._auth_token),
            timeout=10.0,
        ) as client:
            response = await client.post(
                "/Messages.json",
                data={"To": to_phone, "From": self._from_number, "Body": body},
            )
            response.raise_for_status()

    @classmethod
    def from_settings(cls, settings: Settings) -> "TwilioSmsProvider":
        return cls(
            account_sid=settings.twilio_account_sid,
            auth_token=settings.twilio_auth_token,
            from_number=settings.twilio_sms_from_number,
        )
