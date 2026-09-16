import hashlib
import hmac
import json
import uuid
from typing import Any

import httpx

from app.core.config import Settings
from app.domain.billing.interfaces import PaymentInitiation, PaymentProvider, PaymentWebhookResult


class StitchPaymentProvider(PaymentProvider):
    """
    Real adapter — Stitch's Pay-by-Bank API (docs/adr/0012). OAuth2
    client-credentials grant against Stitch's auth server, then a
    GraphQL mutation to create a payment-initiation request whose
    returned URL the client redirects the user to.

    **Exact mutation/field names and the webhook signature header below
    are unverified against a live Stitch account** — written without one
    to test against, the same caveat `services/kyc/smile_id.py` already
    carries for Smile ID. Re-verify against Stitch's current API
    reference (api.stitch.money) before this goes live — see
    docs/SECURITY_GAPS.md.
    """

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        webhook_secret: str,
        auth_url: str,
        api_base_url: str,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._webhook_secret = webhook_secret
        self._auth_url = auth_url
        self._api_base_url = api_base_url

    @classmethod
    def from_settings(cls, settings: Settings) -> "StitchPaymentProvider":
        return cls(
            client_id=settings.stitch_client_id,
            client_secret=settings.stitch_client_secret,
            webhook_secret=settings.stitch_webhook_secret,
            auth_url=settings.stitch_auth_url,
            api_base_url=settings.stitch_api_base_url,
        )

    async def _access_token(self, client: httpx.AsyncClient) -> str:
        response = await client.post(
            self._auth_url,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "client_credentials",
                "audience": "https://finsec.stitch.money",
                "scope": "client_paymentrequest",
            },
        )
        response.raise_for_status()
        token: str = response.json()["access_token"]
        return token

    async def initiate_payment(
        self, *, user_id: uuid.UUID, amount_cents: int, currency: str, description: str
    ) -> PaymentInitiation:
        external_reference = f"ditsala-vip-{user_id}-{uuid.uuid4().hex[:8]}"
        mutation = """
            mutation CreatePaymentRequest($input: ClientPaymentInitiationRequestCreateInput!) {
              clientPaymentInitiationRequestCreate(input: $input) {
                paymentInitiationRequest {
                  id
                  url
                }
              }
            }
        """
        variables = {
            "input": {
                "amount": {"quantity": amount_cents / 100, "currency": currency},
                "payerReference": external_reference,
                "beneficiaryReference": "DITSALA",
                "externalReference": external_reference,
                "description": description,
            }
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            access_token = await self._access_token(client)
            response = await client.post(
                f"{self._api_base_url}/graphql",
                json={"query": mutation, "variables": variables},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            body = response.json()
        request = body["data"]["clientPaymentInitiationRequestCreate"]["paymentInitiationRequest"]
        return PaymentInitiation(payment_url=request["url"], external_reference=external_reference)

    def verify_and_parse_webhook(
        self, *, payload: bytes, signature: str
    ) -> PaymentWebhookResult | None:
        expected = hmac.new(self._webhook_secret.encode(), payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return None
        data: dict[str, Any] = json.loads(payload)
        return PaymentWebhookResult(
            external_reference=data["externalReference"],
            status=data["status"],
            raw=data,
        )
