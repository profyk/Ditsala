"""
Admin call-governance response/request shapes — same "third, admin-only
view" reasoning as `app/schemas/admin_meetings.py`. See
`app/domain/admin/calls_governance.py`.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AdminCallResponse(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID | None
    initiator_user_id: uuid.UUID
    type: str
    status: str
    started_at: datetime | None
    ended_at: datetime | None

    model_config = {"from_attributes": True}


class AdminEndCallRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
