"""
Provider selection — env var only, never a business-logic branch
(docs/DITSALA_MASTER_SPEC.md §3.4, Working Rule 2). Each `get_*_provider`
raises on an unrecognized value rather than silently falling back, so a
typo'd env var fails loudly at startup instead of quietly picking sandbox.
"""

from app.core.config import Settings
from app.domain.messaging.interfaces import StorageProvider
from app.domain.notifications.interfaces import PushProvider, SmsProvider
from app.domain.onboarding.interfaces import EmailProvider, KycProvider, OtpProvider
from app.services.email.resend import ResendEmailProvider
from app.services.email.sandbox import SandboxEmailProvider
from app.services.kyc.bypass import BypassKycProvider
from app.services.kyc.sandbox import SandboxSmileIdProvider
from app.services.kyc.smile_id import SmileIdProvider
from app.services.otp.sandbox import SandboxTwilioProvider
from app.services.otp.twilio_verify import TwilioVerifyProvider
from app.services.push.expo import ExpoPushProvider
from app.services.push.sandbox import SandboxPushProvider
from app.services.sms.sandbox import SandboxSmsProvider
from app.services.sms.twilio_sms import TwilioSmsProvider
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
    if settings.kyc_provider == "bypass":
        # Test-only escape hatch (docs/SECURITY_GAPS.md) for exercising
        # signup/login without a real Smile ID account or native SDK —
        # refused outright in production, no matter how it got configured.
        if settings.environment == "production":
            raise ValueError("KYC_PROVIDER=bypass must never be used with ENVIRONMENT=production.")
        return BypassKycProvider.from_settings(settings)
    raise ValueError(f"Unrecognized KYC_PROVIDER: {settings.kyc_provider!r}")


def get_storage_provider(settings: Settings) -> StorageProvider:
    if settings.storage_provider == "real":
        return S3StorageProvider.from_settings(settings)
    if settings.storage_provider == "sandbox":
        return SandboxStorageProvider.from_settings(settings)
    raise ValueError(f"Unrecognized STORAGE_PROVIDER: {settings.storage_provider!r}")


def get_push_provider(settings: Settings) -> PushProvider:
    if settings.push_provider == "real":
        return ExpoPushProvider.from_settings(settings)
    if settings.push_provider == "sandbox":
        return SandboxPushProvider()
    raise ValueError(f"Unrecognized PUSH_PROVIDER: {settings.push_provider!r}")


def get_sms_provider(settings: Settings) -> SmsProvider:
    if settings.sms_provider == "real":
        return TwilioSmsProvider.from_settings(settings)
    if settings.sms_provider == "sandbox":
        return SandboxSmsProvider.from_settings(settings)
    raise ValueError(f"Unrecognized SMS_PROVIDER: {settings.sms_provider!r}")
