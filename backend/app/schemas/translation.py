import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class LanguageResponse(BaseModel):
    code: str
    name: str


class LanguagePreferencesResponse(BaseModel):
    preferred_language: str
    auto_detect_language: bool
    translate_incoming: bool
    translate_outgoing: bool
    updated_at: datetime

    model_config = {"from_attributes": True}


class SetLanguagePreferencesRequest(BaseModel):
    preferred_language: str = Field(min_length=2, max_length=16)
    auto_detect_language: bool = False
    translate_incoming: bool = True
    translate_outgoing: bool = True


class TranslationResultResponse(BaseModel):
    """Matches item 5's exact structured shape."""

    id: uuid.UUID
    source_text: str
    translated_text: str | None
    source_language: str | None
    target_language: str
    provider: str | None
    status: str
    error_message: str | None

    model_config = {"from_attributes": True}


class CreateInterpreterSessionRequest(BaseModel):
    my_language: str = Field(min_length=2, max_length=16)
    other_language: str = Field(min_length=2, max_length=16)


class InterpreterSessionResponse(BaseModel):
    id: uuid.UUID
    my_language: str
    other_language: str
    created_at: datetime

    model_config = {"from_attributes": True}


class InterpreterTranslateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    # Defaults to the session's my_language -> other_language; either side
    # can flip direction on a given turn (a reply comes back the other way).
    direction: str = Field(default="forward", pattern="^(forward|reverse)$")


class VipUsageResponse(BaseModel):
    request_count: int
    character_count: int
