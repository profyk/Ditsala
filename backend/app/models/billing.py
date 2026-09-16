"""
VIP subscriptions — docs/adr/0012-normal-vip-tier-split.md. Payment
happens first (via Stitch), then the same KYC steps onboarding always
had (reusing `kyc_documents`/`kyc_face_verifications`, tagged
`purpose="vip_upgrade"`) — this table tracks that sequence for an
already-`active` user without touching `users.account_state`, which
stays `active` throughout.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

VIP_SUBSCRIPTION_STATUSES = (
    "pending_payment",
    "awaiting_kyc",
    "active",
    "cancelled",
    "expired",
    "failed",
)


class VipSubscription(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "vip_subscriptions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(
        Enum(
            *VIP_SUBSCRIPTION_STATUSES,
            name="vip_subscription_status",
            native_enum=False,
            validate_strings=True,
        ),
        default="pending_payment",
        server_default=text("'pending_payment'"),
    )
    payment_provider: Mapped[str] = mapped_column(
        String(32), default="stitch", server_default=text("'stitch'")
    )
    # Stitch's own payment/charge identifier — the join key its webhook
    # calls back with.
    external_payment_reference: Mapped[str] = mapped_column(String(128), unique=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
