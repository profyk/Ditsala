import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class FileDataSubjectRequestRequest(BaseModel):
    request_type: str = Field(pattern="^(access|correction|deletion)$")
    details: str | None = None


class DataSubjectRequestResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    request_type: str
    status: str
    details: str | None
    due_at: datetime
    resolved_at: datetime | None
    resolution_notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ResolveDataSubjectRequestRequest(BaseModel):
    resolution_notes: str = Field(min_length=1)
