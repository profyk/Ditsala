from datetime import date

from pydantic import BaseModel, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    phone: str = Field(min_length=8, max_length=32)
    display_name: str = Field(min_length=1, max_length=120)
    date_of_birth: date
    # Raw national ID — hashed server-side before it ever reaches a query
    # or a log line. Never persisted or logged in this form. See §5.
    national_id: str = Field(min_length=4, max_length=64)


class OnboardingSessionResponse(BaseModel):
    onboarding_token: str
    account_state: str


class CodeConfirmRequest(BaseModel):
    code: str = Field(min_length=4, max_length=8)


class KycDocumentStartRequest(BaseModel):
    document_type: str = Field(pattern="^(sa_id|passport)$")


class KycSdkTokenResponse(BaseModel):
    token: str
    job_id: str


class NextOfKinRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    relationship: str = Field(min_length=1, max_length=60)
    phone: str = Field(min_length=8, max_length=32)
    email: EmailStr | None = None


class DitsalaCodeRequest(BaseModel):
    code: str = Field(min_length=8, max_length=128)


class AccountStateResponse(BaseModel):
    account_state: str
