import httpx

from app.core.config import Settings
from app.domain.onboarding.interfaces import OtpProvider


class TwilioVerifyProvider(OtpProvider):
    """
    Real adapter — Twilio Verify's REST API (docs/DITSALA_MASTER_SPEC.md
    §3.4). We never generate or store the code itself, only Twilio's
    verification SID and status (§11). Not exercised in this environment
    (no vendor account) — see CLAUDE.md "Phase 2" notes.
    """

    def __init__(self, *, account_sid: str, auth_token: str, verify_service_sid: str) -> None:
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._verify_service_sid = verify_service_sid

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=f"https://verify.twilio.com/v2/Services/{self._verify_service_sid}",
            auth=(self._account_sid, self._auth_token),
            timeout=10.0,
        )

    async def start_verification(self, *, phone_number: str) -> str:
        async with self._client() as client:
            response = await client.post(
                "/Verifications", data={"To": phone_number, "Channel": "sms"}
            )
            response.raise_for_status()
            sid: str = response.json()["sid"]
            return sid

    async def check_verification(self, *, phone_number: str, code: str) -> bool:
        async with self._client() as client:
            response = await client.post(
                "/VerificationCheck", data={"To": phone_number, "Code": code}
            )
            response.raise_for_status()
            status: str = response.json()["status"]
            return status == "approved"

    @classmethod
    def from_settings(cls, settings: Settings) -> "TwilioVerifyProvider":
        return cls(
            account_sid=settings.twilio_account_sid,
            auth_token=settings.twilio_auth_token,
            verify_service_sid=settings.twilio_verify_service_sid,
        )
