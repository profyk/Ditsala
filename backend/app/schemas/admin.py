import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# --- auth ---


class AdminLoginRequest(BaseModel):
    email: str
    password: str


class AdminLoginStartResponse(BaseModel):
    status: Literal["mfa_enroll_required", "mfa_code_required"]
    mfa_enroll_token: str | None = None
    provisioning_uri: str | None = None
    login_token: str | None = None


class AdminEnrollMfaRequest(BaseModel):
    enroll_token: str
    code: str = Field(min_length=6, max_length=6)


class AdminCompleteLoginRequest(BaseModel):
    login_token: str
    code: str = Field(min_length=6, max_length=6)


class AdminSessionResponse(BaseModel):
    access_token: str
    email: str
    role: str


class AdminMeResponse(BaseModel):
    email: str
    role: str


# --- dashboard ---


class DashboardSummaryResponse(BaseModel):
    signups_today: int
    signups_this_week: int
    active_accounts: int
    manual_review_count: int
    open_reports_count: int
    pending_invitations: int


# --- users ---


class UserSummaryResponse(BaseModel):
    id: uuid.UUID
    email: str
    phone: str
    display_name: str
    account_state: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ForceAccountStateRequest(BaseModel):
    new_state: str
    reason: str = Field(min_length=1, max_length=1000)


class AuditLogEntryResponse(BaseModel):
    id: uuid.UUID
    created_at: datetime
    actor_type: str
    actor_id: uuid.UUID | None
    action: str
    target_type: str | None
    target_id: uuid.UUID | None
    metadata_json: dict[str, Any] | None

    model_config = {"from_attributes": True}


# --- reports ---


class ReportResponse(BaseModel):
    id: uuid.UUID
    reporter_user_id: uuid.UUID
    reported_user_id: uuid.UUID
    reason: str
    context_ref: str | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ActionReportRequest(BaseModel):
    action: Literal["warn", "suspend", "ban"]
    reason: str = Field(min_length=1, max_length=1000)


# --- security ---


class SecuritySummaryResponse(BaseModel):
    locked_accounts: int
    failed_logins_last_24h: int
    active_sessions: int
    new_devices_last_24h: int


# --- invitations ---


class InviteOnlyModeResponse(BaseModel):
    enabled: bool


class SetInviteOnlyModeRequest(BaseModel):
    enabled: bool
    reason: str = Field(min_length=1, max_length=1000)


class InvitationStatsResponse(BaseModel):
    sent: int
    redeemed: int
    expired: int
    top_inviters: list[dict[str, Any]]


# --- system config ---


class SystemConfigResponse(BaseModel):
    key: str
    value: dict[str, Any]
    updated_at: datetime
    updated_by_admin_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class SetSystemConfigRequest(BaseModel):
    value: dict[str, Any]
    reason: str = Field(min_length=1, max_length=1000)


# --- KYC review ---


class KycDocumentResponse(BaseModel):
    id: uuid.UUID
    document_type: str
    status: str
    result_summary: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}


class KycFaceVerificationResponse(BaseModel):
    id: uuid.UUID
    selfie_liveness_score: float | None
    face_match_score: float | None
    status: str
    verified_at: datetime | None

    model_config = {"from_attributes": True}


class KycDetailResponse(BaseModel):
    user: UserSummaryResponse
    documents: list[KycDocumentResponse]
    face_verifications: list[KycFaceVerificationResponse]


class KycActionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
