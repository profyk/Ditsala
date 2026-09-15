"""
Provider selection — env var only, never a business-logic branch
(docs/DITSALA_MASTER_SPEC.md §3.4, Working Rule 2). Each `get_*_provider`
raises on an unrecognized value rather than silently falling back, so a
typo'd env var fails loudly at startup instead of quietly picking sandbox.
"""

from app.core.config import Settings
from app.domain.messaging.interfaces import StorageProvider
from app.domain.onboarding.interfaces import EmailProvider, KycProvider, OtpProvider
from app.services.email.resend import ResendEmailProvider
from app.services.email.sandbox import SandboxEmailProvider
from app.services.kyc.sandbox import SandboxSmileIdProvider
from app.services.kyc.smile_id import SmileIdProvider
from app.services.otp.sandbox import SandboxTwilioProvider
from app.services.otp.twilio_verify import TwilioVerifyProvider
from app.services.storage.s3 import S3StorageProvider
from app.services.storage.sandbox import SandboxStorageProvider


def get_email_provider(settings: Settings) -> EmailProvider:
    if settings.email_provider == "resend":
        return ResendEmailProvider(settings)
    if settings.email_provider == "sandbox":
        return SandboxEmailProvider(settings)
    raise ValueError(f"Unrecognized EMAIL_PROVIDER: {settings.email_provider!r}")


def get_otp_provider(settings: Settings) -> OtpProvider:
    if settings.otp_provider == "twilio":
        return TwilioVerifyProvider.from_settings(settings)
    if settings.otp_provider == "sandbox":
        return SandboxTwilioProvider.from_settings(settings)
    raise ValueError(f"Unrecognized OTP_PROVIDER: {settings.otp_provider!r}")


def get_kyc_provider(settings: Settings) -> KycProvider:
    if settings.kyc_provider == "smile_id":
        return SmileIdProvider.from_settings(settings)
    if settings.kyc_provider == "sandbox":
        return SandboxSmileIdProvider.from_settings(settings)
    raise ValueError(f"Unrecognized KYC_PROVIDER: {settings.kyc_provider!r}")


def get_storage_provider(settings: Settings) -> StorageProvider:
    if settings.storage_provider == "real":
        return S3StorageProvider.from_settings(settings)
    if settings.storage_provider == "sandbox":
        return SandboxStorageProvider.from_settings(settings)
    raise ValueError(f"Unrecognized STORAGE_PROVIDER: {settings.storage_provider!r}")
