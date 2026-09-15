from app.core.config import Settings
from app.services.sms.twilio_sms import TwilioSmsProvider


class SandboxSmsProvider(TwilioSmsProvider):
    """
    Sandbox adapter — same Twilio Messaging REST contract as the real
    adapter, pointed at the account's test credentials (the same
    `TWILIO_TEST_ACCOUNT_SID`/`TWILIO_TEST_AUTH_TOKEN` pair already used
    for OTP sandbox testing — Twilio test credentials work across its
    APIs, not just Verify). Real sandbox capability, unlike push (see
    `services/push/sandbox.py` for why that one differs).
    """

    @classmethod
    def from_settings(cls, settings: Settings) -> "SandboxSmsProvider":
        return cls(
            account_sid=settings.twilio_test_account_sid,
            auth_token=settings.twilio_test_auth_token,
            from_number=settings.twilio_test_sms_from_number,
        )
