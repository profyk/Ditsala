import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.v1.deps import CircleServiceDep, CurrentUserDep
from app.domain.circle.service import CircleError
from app.schemas.circle import (
    BlockUserRequest,
    ContactRequestListItem,
    ContactRequestResponse,
    ContactResponse,
    CreateInvitationRequest,
    InvitationResponse,
    MatchContactsRequest,
    MatchedContactResponse,
    ReportResponse,
    ReportUserRequest,
    SendContactRequestRequest,
    VerifySafetyNumberRequest,
    contact_request_response,
    invitation_response,
)

router = APIRouter(prefix="/circle", tags=["circle"])


def _as_http_error(exc: CircleError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


# --- §22: contact requests ---


@router.post("/contacts/match", response_model=list[MatchedContactResponse])
async def match_contacts(
    body: MatchContactsRequest, user: CurrentUserDep, service: CircleServiceDep
) -> list[MatchedContactResponse]:
    try:
        matches = await service.match_contacts(requesting_user_id=user.id, phones=body.phones)
    except CircleError as exc:
        raise _as_http_error(exc) from exc
    return [MatchedContactResponse.from_user(u) for u in matches]


@router.post("/requests", response_model=ContactRequestResponse, status_code=201)
async def send_contact_request(
    body: SendContactRequestRequest, user: CurrentUserDep, service: CircleServiceDep
) -> ContactRequestResponse:
    try:
        request = await service.send_contact_request(
            from_user_id=user.id, to_user_id=body.to_user_id, channel=body.channel
        )
    except CircleError as exc:
        raise _as_http_error(exc) from exc
    return contact_request_response(request)


@router.post("/requests/{request_id}/accept", response_model=ContactRequestResponse)
async def accept_contact_request(
    request_id: uuid.UUID, user: CurrentUserDep, service: CircleServiceDep
) -> ContactRequestResponse:
    try:
        request = await service.accept_contact_request(
            request_id=request_id, acting_user_id=user.id
        )
    except CircleError as exc:
        raise _as_http_error(exc) from exc
    return contact_request_response(request)


@router.post("/requests/{request_id}/decline", response_model=ContactRequestResponse)
async def decline_contact_request(
    request_id: uuid.UUID, user: CurrentUserDep, service: CircleServiceDep
) -> ContactRequestResponse:
    try:
        request = await service.decline_contact_request(
            request_id=request_id, acting_user_id=user.id
        )
    except CircleError as exc:
        raise _as_http_error(exc) from exc
    return contact_request_response(request)


@router.get("/requests/incoming", response_model=list[ContactRequestListItem])
async def list_incoming_requests(
    user: CurrentUserDep, service: CircleServiceDep
) -> list[ContactRequestListItem]:
    requests = await service.list_incoming_requests(user.id)
    return [ContactRequestListItem.from_model(r) for r in requests]


@router.get("/requests/outgoing", response_model=list[ContactRequestListItem])
async def list_outgoing_requests(
    user: CurrentUserDep, service: CircleServiceDep
) -> list[ContactRequestListItem]:
    requests = await service.list_outgoing_requests(user.id)
    return [ContactRequestListItem.from_model(r) for r in requests]


# --- §22-23: contacts & trust tiers ---


@router.get("/contacts", response_model=list[ContactResponse])
async def list_contacts(user: CurrentUserDep, service: CircleServiceDep) -> list[ContactResponse]:
    contacts = await service.list_contacts(user.id)
    return [ContactResponse.from_model(c) for c in contacts]


@router.get("", response_model=list[ContactResponse])
async def list_circle(user: CurrentUserDep, service: CircleServiceDep) -> list[ContactResponse]:
    """Trusted-tier only — the UI's 'Circle' (§22-23)."""
    contacts = await service.list_circle(user.id)
    return [ContactResponse.from_model(c) for c in contacts]


@router.post("/safety-number/verify", response_model=ContactResponse)
async def verify_safety_number(
    body: VerifySafetyNumberRequest, user: CurrentUserDep, service: CircleServiceDep
) -> ContactResponse:
    try:
        contact = await service.verify_safety_number(
            user_id=user.id, contact_user_id=body.contact_user_id
        )
    except CircleError as exc:
        raise _as_http_error(exc) from exc
    return ContactResponse.from_model(contact)


# --- §24: block & report ---


@router.post("/block/{target_user_id}", status_code=204)
async def block_user(
    target_user_id: uuid.UUID,
    body: BlockUserRequest,
    user: CurrentUserDep,
    service: CircleServiceDep,
) -> None:
    await service.block_user(user_id=user.id, target_user_id=target_user_id, reason=body.reason)


@router.delete("/block/{target_user_id}", status_code=204)
async def unblock_user(
    target_user_id: uuid.UUID, user: CurrentUserDep, service: CircleServiceDep
) -> None:
    await service.unblock_user(user_id=user.id, target_user_id=target_user_id)


@router.post("/report", response_model=ReportResponse, status_code=201)
async def report_user(
    body: ReportUserRequest, user: CurrentUserDep, service: CircleServiceDep
) -> ReportResponse:
    report = await service.report_user(
        reporter_user_id=user.id,
        reported_user_id=body.reported_user_id,
        reason=body.reason,
        context_ref=body.context_ref,
    )
    return ReportResponse.from_model(report)


# --- §22: invitations ---


@router.post("/invitations", response_model=InvitationResponse, status_code=201)
async def create_invitation(
    body: CreateInvitationRequest, user: CurrentUserDep, service: CircleServiceDep
) -> InvitationResponse:
    invitation = await service.create_invitation(inviter_user_id=user.id, channel=body.channel)
    return invitation_response(invitation)
