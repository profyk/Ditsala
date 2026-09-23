import uuid
from datetime import datetime

from pydantic import BaseModel, Field, computed_field


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
    export_storage_key: str | None = Field(exclude=True, default=None)

    model_config = {"from_attributes": True}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def export_available(self) -> bool:
        return self.export_storage_key is not None


class ResolveDataSubjectRequestRequest(BaseModel):
    resolution_notes: str = Field(min_length=1)


class DataExportDownloadResponse(BaseModel):
    download_url: str
