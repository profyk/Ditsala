from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Env-driven configuration. Never hardcode secrets — see .env.example."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "local"
    database_url: str = "postgresql+asyncpg://ditsala:ditsala@localhost:5432/ditsala"
    redis_url: str = "redis://localhost:6379/0"

    # Provider selection — real vs. sandbox, see docs/DITSALA_MASTER_SPEC.md §3.4
    kyc_provider: str = "sandbox"
    otp_provider: str = "sandbox"
    email_provider: str = "sandbox"

    # 32+ bytes even as a placeholder — HS256 warns below that length, and
    # a real deployment must override this via env var regardless.
    jwt_secret: str = "change-me-in-env-to-a-real-32-byte-secret"
    access_token_ttl_minutes: int = 15
    # Separate from jwt_secret deliberately — key separation between "signs
    # tokens" and "hashes PII for dedup lookup" so rotating one never
    # silently affects the other.
    national_id_pepper: str = "change-me-in-env-to-a-real-32-byte-secret"

    # --- Resend (real EmailProvider) ---
    resend_api_key: str = ""
    resend_from_address: str = "DITSALA <no-reply@ditsala.app>"

    # --- Sandbox EmailProvider: local SMTP catcher (e.g. Mailpit) ---
    sandbox_smtp_host: str = "127.0.0.1"
    sandbox_smtp_port: int = 1025
    sandbox_from_address: str = "no-reply@ditsala.local"

    # --- Twilio Verify (OtpProvider). Test credentials are a distinct,
    # Twilio-documented account pair that exercises the same API without
    # sending real SMS or incurring cost — the OtpProvider sandbox
    # adapter, not a hand-rolled fake. ---
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_verify_service_sid: str = ""
    twilio_test_account_sid: str = ""
    twilio_test_auth_token: str = ""
    twilio_test_verify_service_sid: str = ""

    # --- Smile ID (KycProvider). Sandbox uses a distinct API host, per
    # Smile ID's own documented test environment. ---
    smile_id_partner_id: str = ""
    smile_id_api_key: str = ""
    smile_id_api_base_url: str = "https://api.smileidentity.com/v1"
    smile_id_sandbox_partner_id: str = ""
    smile_id_sandbox_api_key: str = ""
    smile_id_sandbox_api_base_url: str = "https://testapi.smileidentity.com/v1"
    smile_id_callback_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
