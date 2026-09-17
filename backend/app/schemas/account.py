from datetime import datetime

from pydantic import BaseModel, Field


class AccountDeactivationResponse(BaseModel):
    account_state: str
    deactivated_at: datetime | None
    hard_delete_after: datetime | None

    model_config = {"from_attributes": True}


class RequestAvatarUploadRequest(BaseModel):
    content_type: str = Field(pattern="^image/(jpeg|png|webp)$")


class RequestAvatarUploadResponse(BaseModel):
    key: str
    upload_url: str


class ConfirmAvatarRequest(BaseModel):
    key: str = Field(min_length=1, max_length=512)


class AvatarResponse(BaseModel):
    avatar_url: str | None
