import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TriggerSosRequest(BaseModel):
    last_known_location_ref: str | None = Field(default=None, max_length=256)


class SosEventResponse(BaseModel):
    id: uuid.UUID
    triggered_at: datetime
    cancel_window_seconds: int
    cancelled_at: datetime | None
    status: str

    model_config = {"from_attributes": True}


class SosNotificationResponse(BaseModel):
    notified_user_id: uuid.UUID
    notified_at: datetime
    channel: str

    model_config = {"from_attributes": True}
