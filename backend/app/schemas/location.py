import uuid
from datetime import datetime

from pydantic import BaseModel, Field

MAX_SHARE_DURATION_SECONDS = 24 * 60 * 60  # 24h — a fresh grant renews, never auto-extends (§25)


class CreateLocationShareRequest(BaseModel):
    recipient_user_id: uuid.UUID
    duration_seconds: int = Field(gt=0, le=MAX_SHARE_DURATION_SECONDS)


class LocationShareResponse(BaseModel):
    id: uuid.UUID
    sharer_user_id: uuid.UUID
    recipient_user_id: uuid.UUID
    starts_at: datetime
    expires_at: datetime
    revoked_at: datetime | None

    model_config = {"from_attributes": True}


class RecordPingRequest(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float = Field(ge=0)


class LocationPingResponse(BaseModel):
    id: uuid.UUID
    lat: float
    lng: float
    accuracy_m: float
    recorded_at: datetime

    model_config = {"from_attributes": True}


class LocationAccessLogResponse(BaseModel):
    accessed_by_user_id: uuid.UUID
    accessed_at: datetime

    model_config = {"from_attributes": True}
