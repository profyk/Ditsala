import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.v1.admin_deps import (
    AdminMessagingGovernanceServiceDep,
    CurrentAdminDep,
    require_permission,
)
from app.domain.admin.messaging_governance import MessagingGovernanceError
from app.domain.admin.rbac import Permission
from app.schemas.admin_messaging import (
    AdminConversationDetailResponse,
    AdminConversationListResponse,
    AdminConversationSummaryResponse,
    AdminDeleteMessageRequest,
    AdminMessageContextResponse,
    AdminRemoveMemberRequest,
)

router = APIRouter(
    prefix="/admin/messaging",
    tags=["admin-messaging"],
    dependencies=[require_permission(Permission.MESSAGING_GOVERNANCE_VIEW)],
)


def _as_http_error(exc: MessagingGovernanceError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.get("/conversations", response_model=AdminConversationListResponse)
async def list_conversations(
    service: AdminMessagingGovernanceServiceDep,
    limit: Annotated[int, Query(le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AdminConversationListResponse:
    """Every conversation platform-wide, metadata only — the first place
    in this codebase that lists conversations without a per-user scope.
    See `AdminMessagingGovernanceService`'s docstring for why this is new
    and what §7.3 guarantee it does not touch."""
    items = await service.list_conversations(limit=limit, offset=offset)
    total = await service.count_conversations()
    return AdminConversationListResponse(
        conversations=[AdminConversationSummaryResponse.from_domain(i) for i in items],
        total=total,
    )


@router.get("/conversations/{conversation_id}", response_model=AdminConversationDetailResponse)
async def get_conversation(
    conversation_id: uuid.UUID, service: AdminMessagingGovernanceServiceDep
) -> AdminConversationDetailResponse:
    try:
        detail = await service.get_conversation(conversation_id)
    except MessagingGovernanceError as exc:
        raise _as_http_error(exc) from exc
    return AdminConversationDetailResponse.from_domain(detail)


@router.get("/messages/{message_id}/context", response_model=AdminMessageContextResponse)
async def get_message_context(
    message_id: uuid.UUID, service: AdminMessagingGovernanceServiceDep
) -> AdminMessageContextResponse:
    """Backs a Reports & Moderation reviewer resolving a message-level
    report's `context_ref` — metadata only, never `ciphertext`."""
    try:
        context = await service.get_message_context(message_id)
    except MessagingGovernanceError as exc:
        raise _as_http_error(exc) from exc
    return AdminMessageContextResponse.from_domain(context)


@router.post(
    "/conversations/{conversation_id}/members/{target_user_id}/remove",
    status_code=204,
    dependencies=[require_permission(Permission.MESSAGING_GOVERNANCE_ACTION)],
)
async def remove_member(
    conversation_id: uuid.UUID,
    target_user_id: uuid.UUID,
    body: AdminRemoveMemberRequest,
    admin: CurrentAdminDep,
    service: AdminMessagingGovernanceServiceDep,
) -> None:
    try:
        await service.remove_member(
            admin_id=admin.id,
            conversation_id=conversation_id,
            target_user_id=target_user_id,
            reason=body.reason,
        )
    except MessagingGovernanceError as exc:
        raise _as_http_error(exc) from exc


@router.post(
    "/messages/{message_id}/delete",
    status_code=204,
    dependencies=[require_permission(Permission.MESSAGING_GOVERNANCE_ACTION)],
)
async def delete_message(
    message_id: uuid.UUID,
    body: AdminDeleteMessageRequest,
    admin: CurrentAdminDep,
    service: AdminMessagingGovernanceServiceDep,
) -> None:
    try:
        await service.delete_message(admin_id=admin.id, message_id=message_id, reason=body.reason)
    except MessagingGovernanceError as exc:
        raise _as_http_error(exc) from exc
