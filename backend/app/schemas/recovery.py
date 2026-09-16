import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class StartRecoveryRequest(BaseModel):
    email: str
    phone: str


class RecoveryRequestResponse(BaseModel):
    id: uuid.UUID
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ConfirmCodeRequest(BaseModel):
    recovery_request_id: uuid.UUID
    code: str = Field(min_length=1, max_length=10)


class LivenessStartRequest(BaseModel):
    recovery_request_id: uuid.UUID


class KycSdkTokenResponse(BaseModel):
    token: str
    job_id: str


class CompleteRecoveryRequest(BaseModel):
    recovery_request_id: uuid.UUID
    new_ditsala_code: str = Field(min_length=1, max_length=128)
    device_name: str = Field(min_length=1, max_length=120)
    platform: str = Field(pattern="^(ios|android)$")
    push_token: str | None = None


class CompleteRecoveryResponse(BaseModel):
    access_token: str
    refresh_token: str
    device_id: uuid.UUID


class FlagRecoveryResponse(BaseModel):
    status: str
