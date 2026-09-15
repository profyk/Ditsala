from app.core.config import Settings
from app.services.kyc.smile_id import SmileIdProvider


class SandboxSmileIdProvider(SmileIdProvider):
    """
    Sandbox adapter — Smile ID's own test environment
    (testapi.smileidentity.com, a distinct host from production), used
    with a separate sandbox partner ID/API key rather than a hand-rolled
    fake. See docs/DITSALA_MASTER_SPEC.md §3.4.
    """

    @classmethod
    def from_settings(cls, settings: Settings) -> "SandboxSmileIdProvider":
        return cls(
            partner_id=settings.smile_id_sandbox_partner_id,
            api_key=settings.smile_id_sandbox_api_key,
            base_url=settings.smile_id_sandbox_api_base_url,
            callback_url=settings.smile_id_callback_url,
        )
