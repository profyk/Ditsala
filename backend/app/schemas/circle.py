import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.circle.service import (
    CONTACT_MATCH_MAX_PHONES,
    ContactRequestWithProfiles,
    ContactWithProfile,
)
from app.models.accounts import User
from app.models.circle import ContactRequest, Invitation, Report


class SendContactRequestRequest(BaseModel):
    to_user_id: uuid.UUID
    channel: str = Field(pattern="^(qr|invite_link|phone_match)$")


class MatchContactsRequest(BaseModel):
    phones: list[str] = Field(min_length=1, max_length=CONTACT_MATCH_MAX_PHONES)


class MatchedContactResponse(BaseModel):
    user_id: uuid.UUID
    display_name: str
    avatar_url: str | None

    @classmethod
    def from_user(cls, user: User) -> "MatchedContactResponse":
        return cls(user_id=user.id, display_name=user.display_name, avatar_url=None)


class ContactRequestResponse(BaseModel):
    id: uuid.UUID
    from_user_id: uuid.UUID
    to_user_id: uuid.UUID
    status: str
    channel: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ContactRequestListItem(BaseModel):
    id: uuid.UUID
    from_user_id: uuid.UUID
    to_user_id: uuid.UUID
    from_user_display_name: str
    to_user_display_name: str
    status: str
    channel: str
    created_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, item: ContactRequestWithProfiles) -> "ContactRequestListItem":
        return cls(
            id=item.request.id,
            from_user_id=item.request.from_user_id,
            to_user_id=item.request.to_user_id,
            from_user_display_name=item.from_user_display_name,
            to_user_display_name=item.to_user_display_name,
            status=item.request.status,
            channel=item.request.channel,
            created_at=item.request.created_at,
        )


class ContactResponse(BaseModel):
    id: uuid.UUID
    contact_user_id: uuid.UUID
    contact_display_name: str
    tier: str
    safety_number_verified_at: datetime | None

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, item: ContactWithProfile) -> "ContactResponse":
        return cls(
            id=item.contact.id,
            contact_user_id=item.contact.contact_user_id,
            contact_display_name=item.display_name,
            tier=item.contact.tier,
            safety_number_verified_at=item.contact.safety_number_verified_at,
        )


class VerifySafetyNumberRequest(BaseModel):
    contact_user_id: uuid.UUID


class BlockUserRequest(BaseModel):
    reason: str | None = None


class ReportUserRequest(BaseModel):
    reported_user_id: uuid.UUID
    reason: str = Field(min_length=1, max_length=1000)
    context_ref: str | None = Field(default=None, max_length=256)


class ReportResponse(BaseModel):
    id: uuid.UUID
    reported_user_id: uuid.UUID
    status: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, report: Report) -> "ReportResponse":
        return cls(id=report.id, reported_user_id=report.reported_user_id, status=report.status)


class CreateInvitationRequest(BaseModel):
    channel: str = Field(pattern="^(sms|link)$")


class InvitationResponse(BaseModel):
    id: uuid.UUID
    invite_code: str
    channel: str
    status: str
    expires_at: datetime

    model_config = {"from_attributes": True}


def contact_request_response(request: ContactRequest) -> ContactRequestResponse:
    return ContactRequestResponse.model_validate(request)


def invitation_response(invitation: Invitation) -> InvitationResponse:
    return InvitationResponse.model_validate(invitation)
