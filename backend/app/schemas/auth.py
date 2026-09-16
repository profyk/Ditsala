import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class DeviceRegistrationRequest(BaseModel):
    device_name: str = Field(min_length=1, max_length=120)
    platform: str = Field(pattern="^(ios|android)$")
    push_token: str | None = None


class SessionResponse(BaseModel):
    access_token: str
    refresh_token: str
    device_id: uuid.UUID


class LoginStartRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=320)  # email or phone
    ditsala_code: str = Field(min_length=1, max_length=128)
    device_name: str = Field(min_length=1, max_length=120)
    platform: str = Field(pattern="^(ios|android)$")
    push_token: str | None = None


class LoginStartResponse(BaseModel):
    """ADR 0012: `vip` accounts get the two-factor fields (code already
    checked; still need `login_token`/`kyc_token`/`job_id` to complete
    the liveness step). `normal` accounts get a session directly — the
    code alone was the whole login. Exactly one group is populated,
    selected by `requires_liveness`."""

    requires_liveness: bool
    login_token: str | None = None
    kyc_token: str | None = None
    job_id: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    device_id: uuid.UUID | None = None


class LoginCompleteRequest(BaseModel):
    login_token: str


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str


class DeviceResponse(BaseModel):
    id: uuid.UUID
    device_name: str
    platform: str
    is_trusted: bool
    last_seen_at: datetime
    revoked_at: datetime | None

    model_config = {"from_attributes": True}


class CurrentUserResponse(BaseModel):
    """Minimal 'who am I' — e.g. so the client can render its own QR code
    for Circle's add-contact flow (§22) without decoding its own JWT."""

    id: uuid.UUID
    display_name: str

    model_config = {"from_attributes": True}
