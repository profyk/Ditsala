from app.core.config import Settings
from app.services.billing.stitch import StitchPaymentProvider


class SandboxStitchPaymentProvider(StitchPaymentProvider):
    """
    Sandbox adapter — Stitch's own test environment, a separate
    client_id/secret pair rather than a hand-rolled fake (docs/adr/0012,
    Working Rule 4). Unverified against a live Stitch sandbox account —
    see `services/billing/stitch.py`'s docstring.
    """

    @classmethod
    def from_settings(cls, settings: Settings) -> "SandboxStitchPaymentProvider":
        return cls(
            client_id=settings.stitch_sandbox_client_id,
            client_secret=settings.stitch_sandbox_client_secret,
            webhook_secret=settings.stitch_sandbox_webhook_secret,
            auth_url=settings.stitch_sandbox_auth_url,
            api_base_url=settings.stitch_sandbox_api_base_url,
        )
