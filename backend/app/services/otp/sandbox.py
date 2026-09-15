from app.core.config import Settings
from app.services.otp.twilio_verify import TwilioVerifyProvider


class SandboxTwilioProvider(TwilioVerifyProvider):
    """
    Sandbox adapter — the same Twilio Verify REST contract as the real
    adapter, pointed at a separate credential set. The real/sandbox split
    for Twilio Verify is which Verify Service + account is configured
    (e.g. a trial account, or a Verify Service with Twilio's documented
    test phone numbers configured in the Console), not a different code
    path — so this class exists mainly to make the selection explicit and
    env-var-driven, per docs/DITSALA_MASTER_SPEC.md §3.4.
    """

    @classmethod
    def from_settings(cls, settings: Settings) -> "SandboxTwilioProvider":
        return cls(
            account_sid=settings.twilio_test_account_sid,
            auth_token=settings.twilio_test_auth_token,
            verify_service_sid=settings.twilio_test_verify_service_sid,
        )
