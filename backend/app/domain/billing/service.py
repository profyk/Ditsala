"""
VIP upgrade — docs/adr/0012-normal-vip-tier-split.md. Payment first (via
Stitch), then the same KYC steps onboarding always had (reusing
`KycDocument`/`KycFaceVerification`, tagged `purpose="vip_upgrade"` so
the webhook router and this service can tell those rows apart from an
onboarding-in-progress signup). Deliberately its own service rather than
folded into `OnboardingService`: an upgrading user is already `active`
and never touches `account_state` during this — a different lifecycle
entirely from onboarding's pending_* state machine.

Pricing is admin-configured, not a hardcoded constant — see
`_get_pricing`. An admin must set it via the generic `system_config`
key/value editor (`PUT /admin/system-config/vip_pricing`) before any
upgrade can be initiated.
"""

from datetime import UTC, datetime, timedelta

from app.domain.billing.interfaces import PaymentInitiation, PaymentProvider, PaymentWebhookResult
from app.domain.onboarding.interfaces import (
    KycJobType,
    KycOutcome,
    KycProvider,
    KycSdkToken,
    KycWebhookResult,
)
from app.models.accounts import KycDocument, KycFaceVerification, User
from app.models.billing import VipSubscription
from app.repositories.admin import SystemConfigRepository
from app.repositories.billing import VipSubscriptionRepository
from app.repositories.kyc import KycDocumentRepository, KycFaceVerificationRepository
from app.repositories.users import UserRepository

VIP_PRICING_CONFIG_KEY = "vip_pricing"
# §34.2-style retention isn't relevant here — this is just how long a
# paid VIP period lasts before requiring renewal. A year, not tied to any
# spec section since VIP itself is a business decision, not a compliance one.
VIP_PERIOD_DAYS = 365


class VipUpgradeError(Exception):
    """Raised for VIP-upgrade preconditions a caller should turn into a 4xx, not a 500."""


class VipUpgradeService:
    def __init__(
        self,
        *,
        users: UserRepository,
        vip_subscriptions: VipSubscriptionRepository,
        kyc_documents: KycDocumentRepository,
        kyc_face_verifications: KycFaceVerificationRepository,
        system_config: SystemConfigRepository,
        payment_provider: PaymentProvider,
        kyc_provider: KycProvider,
    ) -> None:
        self._users = users
        self._vip_subscriptions = vip_subscriptions
        self._kyc_documents = kyc_documents
        self._kyc_face_verifications = kyc_face_verifications
        self._system_config = system_config
        self._payment_provider = payment_provider
        self._kyc_provider = kyc_provider

    # --- step 1: payment ---

    async def start_upgrade(
        self,
        user: User,
        *,
        email: str | None = None,
        date_of_birth: datetime | None = None,
        national_id_hash: str | None = None,
    ) -> PaymentInitiation:
        if user.account_tier == "vip":
            raise VipUpgradeError("Account is already VIP.")
        in_progress = await self._vip_subscriptions.get_latest_for_user(user.id)
        if in_progress is not None and in_progress.status in ("pending_payment", "awaiting_kyc"):
            raise VipUpgradeError("A VIP upgrade is already in progress for this account.")

        # ADR 0014: a normal-tier phone-only signup has none of these —
        # VIP identifies by email (its login uses email + PIN, unlike
        # normal's phone + PIN), so upgrading is the real point they get
        # collected. A legacy account that already has them (the old
        # email-first signup path) isn't asked again.
        if user.email is None:
            if email is None or date_of_birth is None or national_id_hash is None:
                raise VipUpgradeError(
                    "Email, date of birth, and national ID are required to upgrade to VIP."
                )
            existing = await self._users.get_by_email(email)
            if existing is not None and existing.id != user.id:
                raise VipUpgradeError("An account with this email already exists.")
            user.email = email
            user.date_of_birth = date_of_birth
            user.national_id_hash = national_id_hash

        amount_cents, currency = await self._get_pricing()
        initiation = await self._payment_provider.initiate_payment(
            user_id=user.id,
            amount_cents=amount_cents,
            currency=currency,
            description="DITSALA VIP upgrade",
        )
        await self._vip_subscriptions.add(
            VipSubscription(
                user_id=user.id, external_payment_reference=initiation.external_reference
            )
        )
        return initiation

    async def _get_pricing(self) -> tuple[int, str]:
        config = await self._system_config.get_by_key(VIP_PRICING_CONFIG_KEY)
        if config is None:
            raise VipUpgradeError(
                "VIP pricing has not been configured yet — an admin must set the "
                f"{VIP_PRICING_CONFIG_KEY!r} system_config key before upgrades can start."
            )
        amount_cents = config.value.get("amount_cents")
        currency = config.value.get("currency")
        if not isinstance(amount_cents, int) or not isinstance(currency, str):
            raise VipUpgradeError(
                f"{VIP_PRICING_CONFIG_KEY!r} is misconfigured — expected "
                '{"amount_cents": <int>, "currency": <str>}.'
            )
        return amount_cents, currency

    async def handle_payment_webhook(self, result: PaymentWebhookResult) -> VipSubscription:
        subscription = await self._vip_subscriptions.get_by_external_reference(
            result.external_reference
        )
        if subscription is None:
            raise VipUpgradeError("Unknown payment reference.")
        if result.status == "paid":
            subscription.status = "awaiting_kyc"
            subscription.paid_at = datetime.now(UTC)
            subscription.current_period_end = datetime.now(UTC) + timedelta(days=VIP_PERIOD_DAYS)
        else:
            subscription.status = "failed"
        return subscription

    # --- step 2: KYC (same product as onboarding, tagged separately) ---

    async def _require_awaiting_kyc(self, user: User) -> VipSubscription:
        subscription = await self._vip_subscriptions.get_latest_for_user(user.id)
        if subscription is None or subscription.status != "awaiting_kyc":
            raise VipUpgradeError("Complete VIP payment before starting identity verification.")
        return subscription

    async def start_kyc_document(self, user: User, *, document_type: str) -> KycSdkToken:
        await self._require_awaiting_kyc(user)
        sdk_token = await self._kyc_provider.create_sdk_token(
            user_id=user.id, job_type=KycJobType.DOCUMENT_VERIFICATION
        )
        await self._kyc_documents.add(
            KycDocument(
                user_id=user.id,
                document_type=document_type,
                smile_id_job_id=sdk_token.job_id,
                purpose="vip_upgrade",
            )
        )
        return sdk_token

    async def handle_kyc_document_result(self, result: KycWebhookResult) -> None:
        document = await self._kyc_documents.get_by_smile_id_job(result.job_id)
        if document is None or document.purpose != "vip_upgrade":
            raise VipUpgradeError("Unknown VIP-upgrade document job.")
        document.status = "passed" if result.outcome == KycOutcome.PASSED else "failed"
        document.result_summary = result.result_summary

    async def start_kyc_liveness(self, user: User) -> KycSdkToken:
        await self._require_awaiting_kyc(user)
        latest_document = await self._kyc_documents.get_latest_for_user_and_purpose(
            user.id, purpose="vip_upgrade"
        )
        if latest_document is None or latest_document.status != "passed":
            raise VipUpgradeError("Document verification must pass before liveness.")
        sdk_token = await self._kyc_provider.create_sdk_token(
            user_id=user.id, job_type=KycJobType.SMARTSELFIE
        )
        await self._kyc_face_verifications.add(
            KycFaceVerification(
                user_id=user.id, smile_id_job_id=sdk_token.job_id, purpose="vip_upgrade"
            )
        )
        return sdk_token

    async def handle_kyc_liveness_result(self, result: KycWebhookResult) -> None:
        face = await self._kyc_face_verifications.get_by_smile_id_job(result.job_id)
        if face is None or face.purpose != "vip_upgrade":
            raise VipUpgradeError("Unknown VIP-upgrade liveness job.")
        face.status = "passed" if result.outcome == KycOutcome.PASSED else "failed"
        if face.status != "passed":
            return
        face.verified_at = datetime.now(UTC)

        user = await self._users.get(face.user_id)
        assert user is not None
        user.account_tier = "vip"

        subscription = await self._vip_subscriptions.get_latest_for_user(face.user_id)
        assert subscription is not None
        subscription.status = "active"
