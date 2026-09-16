"""
VIP subscription payments — docs/adr/0012-normal-vip-tier-split.md.
Behind a Protocol like every other external dependency (Working Rule 4).

No live Stitch account exists in this environment (see
docs/SECURITY_GAPS.md) — the real adapter's exact field/endpoint shape
is unverified against a live account, the same caveat already carried
by the Smile ID adapter (`services/kyc/smile_id.py`).
"""

import uuid
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class PaymentInitiation:
    """`payment_url` is where the client redirects the user to actually
    pay (Stitch's own hosted Pay-by-Bank flow) — this backend never
    collects card/bank details itself."""

    payment_url: str
    external_reference: str


@dataclass(frozen=True)
class PaymentWebhookResult:
    external_reference: str
    status: str  # "paid" | "failed" | "cancelled"
    raw: dict[str, Any]


class PaymentProvider(Protocol):
    async def initiate_payment(
        self, *, user_id: uuid.UUID, amount_cents: int, currency: str, description: str
    ) -> PaymentInitiation:
        """Starts a payment and returns where to send the user to complete
        it. Never returns or logs card/bank credentials — this backend
        never sees them, by construction of a redirect-based flow."""
        ...

    def verify_and_parse_webhook(
        self, *, payload: bytes, signature: str
    ) -> PaymentWebhookResult | None:
        """None means the signature didn't verify — the caller must
        reject the request, never fall back to trusting an unsigned
        payload."""
        ...
