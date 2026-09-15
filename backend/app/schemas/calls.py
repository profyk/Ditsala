import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class InitiateCallRequest(BaseModel):
    conversation_id: uuid.UUID
    call_type: str = Field(pattern="^(voice|video)$")


class CallResponse(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID | None
    initiator_user_id: uuid.UUID
    type: str
    status: str
    started_at: datetime | None
    ended_at: datetime | None

    model_config = {"from_attributes": True}


class SwitchMediaRequest(BaseModel):
    call_type: str = Field(pattern="^(voice|video)$")


class CallSignalRequest(BaseModel):
    """`payload` is an opaque WebRTC SDP offer/answer or ICE candidate —
    the backend relays it without inspecting its shape (§7.3, §27)."""

    payload: dict[str, Any]


class IceServer(BaseModel):
    urls: str
    username: str | None = None
    credential: str | None = None


class IceServersResponse(BaseModel):
    ice_servers: list[IceServer]
