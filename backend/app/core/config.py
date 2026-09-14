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

    jwt_secret: str = "change-me-in-env"
    access_token_ttl_minutes: int = 15


@lru_cache
def get_settings() -> Settings:
    return Settings()
