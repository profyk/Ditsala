import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status

from app.api.v1.deps import (
    CurrentDeviceDep,
    CurrentUserDep,
    MessagingServiceDep,
    SessionDep,
    SettingsDep,
    get_current_device_from_ws_token,
    get_messaging_service,
)
from app.domain.messaging.service import MessagingError
from app.models.messaging import Conversation
from app.schemas.messaging import (
    ConversationMemberResponse,
    ConversationResponse,
    CreateGroupConversationRequest,
    EditMessageRequest,
    IdentityKeyRequest,
    MediaDownloadResponse,
    MediaUploadRequest,
    MediaUploadResponse,
    MessageResponse,
    OneTimePrekeysRequest,
    PrekeyBundleResponse,
    PrimaryDeviceResponse,
    ReceiptRequest,
    RenameGroupConversationRequest,
    SenderKeyRequest,
    SenderKeyResponse,
    SendMessageRequest,
    SetDisappearingTimerRequest,
    SetFlagRequest,
    SetMutedRequest,
    SignedPrekeyRequest,
    StartDirectConversationRequest,
    decode_b64,
    encode_b64,
)
from app.services.realtime.websocket_manager import connection_manager

router = APIRouter(prefix="/messaging", tags=["messaging"])


def _as_http_error(exc: MessagingError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


# --- key registration (§6) ---


@router.post("/keys/identity", status_code=204)
async def register_identity_key(
    body: IdentityKeyRequest, device: CurrentDeviceDep, service: MessagingServiceDep
) -> None:
    await service.register_identity_key(
        device,
        public_identity_key=decode_b64(body.public_identity_key),
        registration_id=body.registration_id,
    )


@router.post("/keys/signed-prekey", status_code=204)
async def upload_signed_prekey(
    body: SignedPrekeyRequest, device: CurrentDeviceDep, service: MessagingServiceDep
) -> None:
    await service.upload_signed_prekey(
        device,
        key_id=body.key_id,
        public_key=decode_b64(body.public_key),
        signature=decode_b64(body.signature),
    )


@router.post("/keys/one-time-prekeys", status_code=204)
async def upload_one_time_prekeys(
    body: OneTimePrekeysRequest, device: CurrentDeviceDep, service: MessagingServiceDep
) -> None:
    await service.upload_one_time_prekeys(
        device, keys=[(item.key_id, decode_b64(item.public_key)) for item in body.keys]
    )


@router.get("/keys/prekey-bundle/{user_id}/{device_id}", response_model=PrekeyBundleResponse)
async def get_prekey_bundle(
    user_id: uuid.UUID,
    device_id: uuid.UUID,
    _user: CurrentUserDep,
    service: MessagingServiceDep,
) -> PrekeyBundleResponse:
    try:
        bundle = await service.get_prekey_bundle(user_id=user_id, device_id=device_id)
    except MessagingError as exc:
        raise _as_http_error(exc) from exc
    return PrekeyBundleResponse(
        identity_key=encode_b64(bundle.identity_key),
        registration_id=bundle.registration_id,
        signed_prekey_id=bundle.signed_prekey_id,
        signed_prekey_public=encode_b64(bundle.signed_prekey_public),
        signed_prekey_signature=encode_b64(bundle.signed_prekey_signature),
        one_time_prekey_id=bundle.one_time_prekey_id,
        one_time_prekey_public=(
            encode_b64(bundle.one_time_prekey_public) if bundle.one_time_prekey_public else None
        ),
    )


@router.get("/keys/primary-device/{user_id}", response_model=PrimaryDeviceResponse)
async def get_primary_device(
    user_id: uuid.UUID, _user: CurrentUserDep, service: MessagingServiceDep
) -> PrimaryDeviceResponse:
    """V1 sends to a single device per recipient — see docs/adr/0013's
    multi-device-fan-out gap note."""
    try:
        device_id = await service.get_primary_device_id(user_id)
    except MessagingError as exc:
        raise _as_http_error(exc) from exc
    return PrimaryDeviceResponse(device_id=device_id)


# --- conversations ---


def _conversation_response(
    conversation: Conversation, last_message_at: datetime | None = None
) -> ConversationResponse:
    return ConversationResponse(
        id=conversation.id,
        type=conversation.type,
        title=conversation.title,
        disappearing_timer_seconds=conversation.disappearing_timer_seconds,
        last_message_at=last_message_at,
    )


@router.post("/conversations/direct", response_model=ConversationResponse)
async def start_direct_conversation(
    body: StartDirectConversationRequest, user: CurrentUserDep, service: MessagingServiceDep
) -> ConversationResponse:
    try:
        conversation = await service.start_direct_conversation(user.id, body.other_user_id)
    except MessagingError as exc:
        raise _as_http_error(exc) from exc
    return _conversation_response(conversation)


@router.post("/conversations/group", response_model=ConversationResponse)
async def create_group_conversation(
    body: CreateGroupConversationRequest, user: CurrentUserDep, service: MessagingServiceDep
) -> ConversationResponse:
    conversation = await service.create_group_conversation(
        user.id, body.member_ids, title=body.title
    )
    return _conversation_response(conversation)


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    user: CurrentUserDep, service: MessagingServiceDep
) -> list[ConversationResponse]:
    summaries = await service.list_conversations(user.id)
    return [_conversation_response(s.conversation, s.last_message_at) for s in summaries]


@router.patch("/conversations/{conversation_id}/title", response_model=ConversationResponse)
async def rename_group_conversation(
    conversation_id: uuid.UUID,
    body: RenameGroupConversationRequest,
    user: CurrentUserDep,
    service: MessagingServiceDep,
) -> ConversationResponse:
    try:
        conversation = await service.rename_group_conversation(
            user_id=user.id, conversation_id=conversation_id, title=body.title
        )
    except MessagingError as exc:
        raise _as_http_error(exc) from exc
    return _conversation_response(conversation)


@router.get(
    "/conversations/{conversation_id}/members", response_model=list[ConversationMemberResponse]
)
async def list_conversation_members(
    conversation_id: uuid.UUID, user: CurrentUserDep, service: MessagingServiceDep
) -> list[ConversationMemberResponse]:
    try:
        members = await service.list_conversation_members(
            user_id=user.id, conversation_id=conversation_id
        )
    except MessagingError as exc:
        raise _as_http_error(exc) from exc
    return [ConversationMemberResponse.model_validate(m) for m in members]


@router.patch(
    "/conversations/{conversation_id}/disappearing-timer", response_model=ConversationResponse
)
async def set_disappearing_timer(
    conversation_id: uuid.UUID,
    body: SetDisappearingTimerRequest,
    user: CurrentUserDep,
    service: MessagingServiceDep,
) -> ConversationResponse:
    try:
        conversation = await service.set_disappearing_timer(
            user_id=user.id, conversation_id=conversation_id, seconds=body.seconds
        )
    except MessagingError as exc:
        raise _as_http_error(exc) from exc
    return ConversationResponse.model_validate(conversation)


@router.patch("/conversations/{conversation_id}/muted", status_code=204)
async def set_muted(
    conversation_id: uuid.UUID,
    body: SetMutedRequest,
    user: CurrentUserDep,
    service: MessagingServiceDep,
) -> None:
    try:
        await service.set_muted(
            user_id=user.id, conversation_id=conversation_id, muted_until=body.muted_until
        )
    except MessagingError as exc:
        raise _as_http_error(exc) from exc


@router.patch("/conversations/{conversation_id}/archived", status_code=204)
async def set_archived(
    conversation_id: uuid.UUID,
    body: SetFlagRequest,
    user: CurrentUserDep,
    service: MessagingServiceDep,
) -> None:
    try:
        await service.set_archived(
            user_id=user.id, conversation_id=conversation_id, archived=body.value
        )
    except MessagingError as exc:
        raise _as_http_error(exc) from exc


@router.patch("/conversations/{conversation_id}/pinned", status_code=204)
async def set_pinned(
    conversation_id: uuid.UUID,
    body: SetFlagRequest,
    user: CurrentUserDep,
    service: MessagingServiceDep,
) -> None:
    try:
        await service.set_pinned(
            user_id=user.id, conversation_id=conversation_id, pinned=body.value
        )
    except MessagingError as exc:
        raise _as_http_error(exc) from exc


# --- messages ---


@router.post("/conversations/{conversation_id}/messages", response_model=MessageResponse)
async def send_message(
    conversation_id: uuid.UUID,
    body: SendMessageRequest,
    user: CurrentUserDep,
    device: CurrentDeviceDep,
    service: MessagingServiceDep,
) -> MessageResponse:
    try:
        message = await service.send_message(
            sender_user_id=user.id,
            sender_device_id=device.id,
            conversation_id=conversation_id,
            ciphertext=decode_b64(body.ciphertext),
            content_type=body.content_type,
            client_message_id=body.client_message_id,
            reply_to_message_id=body.reply_to_message_id,
        )
    except MessagingError as exc:
        raise _as_http_error(exc) from exc
    return MessageResponse.from_model(message)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
async def list_messages(
    conversation_id: uuid.UUID,
    user: CurrentUserDep,
    service: MessagingServiceDep,
    before: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(le=200)] = 50,
) -> list[MessageResponse]:
    try:
        messages = await service.list_messages(
            user_id=user.id, conversation_id=conversation_id, before=before, limit=limit
        )
    except MessagingError as exc:
        raise _as_http_error(exc) from exc
    return [MessageResponse.from_model(m) for m in messages]


@router.patch("/messages/{message_id}", response_model=MessageResponse)
async def edit_message(
    message_id: uuid.UUID,
    body: EditMessageRequest,
    user: CurrentUserDep,
    service: MessagingServiceDep,
) -> MessageResponse:
    try:
        message = await service.edit_message(
            user_id=user.id, message_id=message_id, new_ciphertext=decode_b64(body.ciphertext)
        )
    except MessagingError as exc:
        raise _as_http_error(exc) from exc
    return MessageResponse.from_model(message)


@router.delete("/messages/{message_id}", status_code=204)
async def delete_message(
    message_id: uuid.UUID, user: CurrentUserDep, service: MessagingServiceDep
) -> None:
    try:
        await service.delete_message(user_id=user.id, message_id=message_id)
    except MessagingError as exc:
        raise _as_http_error(exc) from exc


@router.post("/messages/{message_id}/receipts", status_code=204)
async def mark_receipt(
    message_id: uuid.UUID,
    body: ReceiptRequest,
    user: CurrentUserDep,
    service: MessagingServiceDep,
) -> None:
    try:
        await service.mark_receipt(user_id=user.id, message_id=message_id, status=body.status)
    except MessagingError as exc:
        raise _as_http_error(exc) from exc


# --- groups: Sender Keys (relay only) ---


@router.post("/conversations/{conversation_id}/sender-keys", status_code=204)
async def upload_sender_key(
    conversation_id: uuid.UUID,
    body: SenderKeyRequest,
    device: CurrentDeviceDep,
    service: MessagingServiceDep,
) -> None:
    try:
        await service.upload_sender_key(
            device=device,
            conversation_id=conversation_id,
            recipient_device_id=body.recipient_device_id,
            distribution_message_ref=decode_b64(body.distribution_message_ref),
        )
    except MessagingError as exc:
        raise _as_http_error(exc) from exc


@router.get("/conversations/{conversation_id}/sender-keys", response_model=list[SenderKeyResponse])
async def list_sender_keys(
    conversation_id: uuid.UUID,
    user: CurrentUserDep,
    device: CurrentDeviceDep,
    service: MessagingServiceDep,
) -> list[SenderKeyResponse]:
    try:
        sender_keys = await service.list_sender_keys(
            user_id=user.id, conversation_id=conversation_id, recipient_device_id=device.id
        )
    except MessagingError as exc:
        raise _as_http_error(exc) from exc
    return [
        SenderKeyResponse(
            device_id=sk.device_id,
            distribution_message_ref=encode_b64(sk.distribution_message_ref),
        )
        for sk in sender_keys
    ]


# --- media ---


@router.post("/media/upload", response_model=MediaUploadResponse)
async def request_media_upload(
    body: MediaUploadRequest, user: CurrentUserDep, service: MessagingServiceDep
) -> MediaUploadResponse:
    try:
        media_object, upload_url = await service.request_media_upload(
            user_id=user.id,
            content_hash=body.content_hash,
            encrypted_size_bytes=body.encrypted_size_bytes,
            content_type=body.content_type,
        )
    except MessagingError as exc:
        raise _as_http_error(exc) from exc
    return MediaUploadResponse(media_object_id=media_object.id, upload_url=upload_url)


@router.get("/media/{media_object_id}/download", response_model=MediaDownloadResponse)
async def get_media_download_url(
    media_object_id: uuid.UUID, user: CurrentUserDep, service: MessagingServiceDep
) -> MediaDownloadResponse:
    try:
        url = await service.get_media_download_url(
            user_id=user.id, media_object_id=media_object_id
        )
    except MessagingError as exc:
        raise _as_http_error(exc) from exc
    return MediaDownloadResponse(download_url=url)


# --- WebSocket transport ---

ws_router = APIRouter(tags=["messaging-ws"])


@ws_router.websocket("/messaging/ws")
async def messaging_ws(
    websocket: WebSocket,
    session: SessionDep,
    settings: SettingsDep,
    token: Annotated[str, Query()],
) -> None:
    try:
        device = await get_current_device_from_ws_token(session, settings, token)
    except ValueError:
        await websocket.close(code=4401)
        return

    service = await get_messaging_service(session, settings)
    await connection_manager.connect(device.id, websocket)
    try:
        while True:
            # Only inbound signal from the client today is typing — new
            # messages/receipts arrive over the REST endpoints above and
            # get pushed out here by MessagingService._notify_conversation.
            data = await websocket.receive_json()
            if data.get("type") == "typing":
                try:
                    conversation_id = uuid.UUID(data["conversation_id"])
                except (KeyError, ValueError):
                    continue
                try:
                    await service.notify_typing(
                        user_id=device.user_id,
                        device_id=device.id,
                        conversation_id=conversation_id,
                    )
                except MessagingError:
                    pass  # not a member — silently drop rather than crash the socket
    except WebSocketDisconnect:
        pass
    finally:
        connection_manager.disconnect(device.id, websocket)
