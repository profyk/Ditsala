import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.v1.deps import CurrentUserDep, VipChatServiceDep
from app.domain.vip_chat.service import VipChatError
from app.schemas.vip_chat import (
    SendVipMessageRequest,
    StartVipConversationRequest,
    VipConversationResponse,
    VipMessageResponse,
    VipMessageTranslationResponse,
)

router = APIRouter(prefix="/vip/conversations", tags=["vip-chat"])


def _as_http_error(exc: VipChatError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.post("", response_model=VipConversationResponse, status_code=201)
async def start_vip_conversation(
    body: StartVipConversationRequest, user: CurrentUserDep, service: VipChatServiceDep
) -> VipConversationResponse:
    try:
        conversation = await service.start_conversation(user, body.other_user_id)
    except VipChatError as exc:
        raise _as_http_error(exc) from exc
    return VipConversationResponse.from_conversation(conversation)


@router.get("", response_model=list[VipConversationResponse])
async def list_vip_conversations(
    user: CurrentUserDep, service: VipChatServiceDep
) -> list[VipConversationResponse]:
    conversations = await service.list_conversations(user.id)
    return [VipConversationResponse.from_conversation(c) for c in conversations]


@router.post("/{conversation_id}/messages", response_model=VipMessageResponse, status_code=201)
async def send_vip_message(
    conversation_id: uuid.UUID,
    body: SendVipMessageRequest,
    user: CurrentUserDep,
    service: VipChatServiceDep,
) -> VipMessageResponse:
    try:
        result = await service.send_message(
            conversation_id=conversation_id,
            sender=user,
            text=body.text,
            client_message_id=body.client_message_id,
        )
    except VipChatError as exc:
        raise _as_http_error(exc) from exc
    return VipMessageResponse.from_domain(result)


@router.get("/{conversation_id}/messages", response_model=list[VipMessageResponse])
async def list_vip_messages(
    conversation_id: uuid.UUID, user: CurrentUserDep, service: VipChatServiceDep
) -> list[VipMessageResponse]:
    try:
        results = await service.list_messages(conversation_id=conversation_id, user_id=user.id)
    except VipChatError as exc:
        raise _as_http_error(exc) from exc
    return [VipMessageResponse.from_domain(r) for r in results]


@router.post(
    "/messages/{message_id}/retry-translation", response_model=VipMessageTranslationResponse
)
async def retry_vip_message_translation(
    message_id: uuid.UUID, user: CurrentUserDep, service: VipChatServiceDep
) -> VipMessageTranslationResponse:
    try:
        translation = await service.retry_translation(message_id=message_id, user_id=user.id)
    except VipChatError as exc:
        raise _as_http_error(exc) from exc
    return VipMessageTranslationResponse(
        target_language=translation.target_language,
        translated_text=translation.translated_text,
        provider=translation.provider,
        status=translation.status,
        error_message=translation.error_message,
    )
