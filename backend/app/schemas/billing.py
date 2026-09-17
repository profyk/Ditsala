from datetime import date

from pydantic import BaseModel, EmailStr, Field


class VipUpgradeStartRequest(BaseModel):
    """ADR 0014 — only meaningful for a normal-tier account that has
    none of these yet (a phone-only signup); ignored if the account
    already has an email."""

    email: EmailStr | None = None
    date_of_birth: date | None = None
    national_id: str | None = Field(default=None, min_length=4, max_length=64)


class VipUpgradeInitiationResponse(BaseModel):
    payment_url: str
    external_reference: str


class VipKycDocumentStartRequest(BaseModel):
    document_type: str = "sa_id"


class VipKycSdkTokenResponse(BaseModel):
    token: str
    job_id: str
