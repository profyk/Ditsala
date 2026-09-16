import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CreateMeetingRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    meeting_type: str = Field(
        default="standard",
        pattern="^(standard|webinar|classroom|interview|town_hall|conference)$",
    )
    scheduled_start_at: datetime | None = None
    scheduled_duration_minutes: int | None = Field(default=None, gt=0)
    password: str | None = None
    waiting_room_enabled: bool = False


class MeetingResponse(BaseModel):
    id: uuid.UUID
    host_user_id: uuid.UUID
    livekit_room_name: str
    title: str
    meeting_type: str
    status: str
    scheduled_start_at: datetime | None
    scheduled_duration_minutes: int | None
    actual_start_at: datetime | None
    actual_end_at: datetime | None
    waiting_room_enabled: bool
    locked_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class JoinMeetingRequest(BaseModel):
    password: str | None = None


class GuestJoinMeetingRequest(BaseModel):
    guest_display_name: str = Field(min_length=1, max_length=120)
    password: str | None = None


class RoomAccessTokenResponse(BaseModel):
    token: str
    livekit_url: str


class JoinMeetingResponse(BaseModel):
    meeting: MeetingResponse
    participant_id: uuid.UUID
    role: str
    access: RoomAccessTokenResponse
