"""
Admin meeting-governance response/request shapes — kept separate from
`app/schemas/admin.py` (already a broad grab-bag of every other admin
concern) and from `app/schemas/meetings.py` (the participant-facing
shapes), since this is a third, admin-only view over meetings. See
`app/domain/admin/meetings_governance.py`.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AdminMeetingResponse(BaseModel):
    id: uuid.UUID
    host_user_id: uuid.UUID
    title: str
    meeting_type: str
    status: str
    scheduled_start_at: datetime | None
    scheduled_duration_minutes: int | None
    actual_start_at: datetime | None
    duration_extended_minutes: int
    max_participants: int | None
    waiting_room_enabled: bool
    locked_at: datetime | None
    active_participant_count: int

    model_config = {"from_attributes": True}


class AdminMeetingParticipantResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    guest_display_name: str | None
    role: str
    admission_status: str
    joined_at: datetime | None
    left_at: datetime | None

    model_config = {"from_attributes": True}


class AdminExtendMeetingRequest(BaseModel):
    additional_minutes: int = Field(gt=0, le=480)
    reason: str = Field(min_length=1, max_length=500)


class AdminEndMeetingRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class AdminParticipantAttendanceResponse(BaseModel):
    participant_id: uuid.UUID
    display_name: str
    role: str
    is_guest: bool
    joined_at: datetime | None
    left_at: datetime | None
    attended_seconds: int


class AdminMeetingAnalyticsResponse(BaseModel):
    meeting_id: uuid.UUID
    as_of: datetime
    total_participant_rows: int
    unique_attendees: int
    guest_attendees: int
    total_attendance_seconds: int
    average_attendance_seconds: float
    peak_concurrent_attendees: int
    attendees: list[AdminParticipantAttendanceResponse]

    model_config = {"from_attributes": True}
