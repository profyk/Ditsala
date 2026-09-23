import uuid

import jwt
from fastapi import APIRouter, HTTPException, status

from app.api.v1.deps import (
    CurrentUserDep,
    MeetingActorDep,
    MeetingIntelligenceServiceDep,
    MeetingServiceDep,
    SessionDep,
    SettingsDep,
)
from app.core.security import create_meet_host_token, decode_meet_host_token
from app.domain.meetings.service import JoinResult, MeetingError
from app.models.meetings import MeetingParticipant
from app.repositories.users import UserRepository
from app.schemas.meetings import (
    AiNoteResponse,
    AskQuestionAboutMeetingRequest,
    AskQuestionAboutMeetingResponse,
    AskQuestionRequest,
    AssignBreakoutRoomRequest,
    BreakoutRoomResponse,
    CreateBreakoutRoomsRequest,
    CreateMeetingRequest,
    CreatePollRequest,
    EditNoteRequest,
    ExtendMeetingRequest,
    GeneratedNotesResponse,
    GuestJoinMeetingRequest,
    HostPinJoinRequest,
    InviteCoHostRequest,
    JoinInfoResponse,
    JoinMeetingRequest,
    JoinMeetingResponse,
    LockMeetingRequest,
    MeetHostJoinRequest,
    MeetHostLinkResponse,
    MeetingAnalyticsResponse,
    MeetingDocumentDownloadResponse,
    MeetingDocumentResponse,
    MeetingDocumentUploadResponse,
    MeetingResponse,
    MeetingSearchResultResponse,
    MessageResponse,
    MuteParticipantRequest,
    ParticipantLanguageResponse,
    ParticipantResponse,
    PollResponse,
    PollResultsResponse,
    QuestionResponse,
    RaiseHandRequest,
    ReactionRequest,
    RecordingResponse,
    RegisterForMeetingRequest,
    RegistrationResponse,
    RequestDocumentUploadRequest,
    RoomAccessTokenResponse,
    SendMessageRequest,
    SetParticipantLanguageRequest,
    SetWaitingRoomRequest,
    TranscriptSegmentResponse,
    TranslateMessageResponse,
    VotePollRequest,
)

router = APIRouter(prefix="/meetings", tags=["meetings"])


def _as_http_error(exc: MeetingError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


def _join_response(result: JoinResult) -> JoinMeetingResponse:
    return JoinMeetingResponse(
        meeting=MeetingResponse.model_validate(result.meeting),
        participant_id=result.participant.id,
        role=result.participant.role,
        admission_status=result.participant.admission_status,
        access=(
            RoomAccessTokenResponse(
                token=result.access_token.token, livekit_url=result.access_token.livekit_url
            )
            if result.access_token is not None
            else None
        ),
    )


async def _current_participant(
    meeting_id: uuid.UUID, user_id: uuid.UUID, service: MeetingServiceDep
) -> MeetingParticipant:
    """Takes a bare `user_id` (not a `CurrentUserDep`-typed `User`) so it
    works from both a real access token (`CurrentUserDep`'s `.id`) and a
    `MeetingActorDep` resolution (host or meet-host-token holder), which
    is a bare `uuid.UUID` already."""
    participant = await service.get_participant_for_user(meeting_id=meeting_id, user_id=user_id)
    if participant is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You are not a participant in this meeting."
        )
    return participant


async def _public_participant(
    meeting_id: uuid.UUID, participant_id: uuid.UUID, service: MeetingServiceDep
) -> MeetingParticipant:
    """The guest-facing counterpart to `_current_participant` above —
    public given a valid participant_id, no JWT required (a guest has no
    DITSALA account). See `MeetingService.assert_participant_in_meeting`'s
    docstring for the trust model this mirrors."""
    try:
        return await service.assert_participant_in_meeting(meeting_id, participant_id)
    except MeetingError as exc:
        raise _as_http_error(exc) from exc


@router.post("", response_model=MeetingResponse, status_code=201)
async def create_meeting(
    body: CreateMeetingRequest, user: CurrentUserDep, service: MeetingServiceDep
) -> MeetingResponse:
    meeting = await service.create_meeting(
        host=user,
        title=body.title,
        meeting_type=body.meeting_type,
        scheduled_start_at=body.scheduled_start_at,
        scheduled_duration_minutes=body.scheduled_duration_minutes,
        password=body.password,
        waiting_room_enabled=body.waiting_room_enabled,
        prep_lead_minutes=body.prep_lead_minutes,
    )
    return MeetingResponse.model_validate(meeting)


@router.get("", response_model=list[MeetingResponse])
async def list_my_meetings(
    user: CurrentUserDep, service: MeetingServiceDep
) -> list[MeetingResponse]:
    meetings = await service.list_hosted_meetings(user.id)
    return [MeetingResponse.model_validate(m) for m in meetings]


@router.get("/search", response_model=list[MeetingSearchResultResponse])
async def search_meetings(
    q: str, user: CurrentUserDep, service: MeetingIntelligenceServiceDep
) -> list[MeetingSearchResultResponse]:
    """§18 — must be registered before `/{meeting_id}` so "search" is
    never parsed as a meeting id."""
    meetings = await service.search_meetings(user_id=user.id, query=q)
    return [MeetingSearchResultResponse.model_validate(m) for m in meetings]


@router.get("/{meeting_id}", response_model=MeetingResponse)
async def get_meeting(
    meeting_id: uuid.UUID, _user: CurrentUserDep, service: MeetingServiceDep
) -> MeetingResponse:
    try:
        meeting = await service.get_meeting(meeting_id)
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return MeetingResponse.model_validate(meeting)


@router.get("/{meeting_id}/join-info", response_model=JoinInfoResponse)
async def get_join_info(meeting_id: uuid.UUID, service: MeetingServiceDep) -> JoinInfoResponse:
    """Public — deliberately no CurrentUserDep: a shared meeting link's
    recipient needs to see the scheduled time / whether a password is
    required before they've authenticated or entered anything (§9
    Phase 4)."""
    try:
        info = await service.get_join_info(meeting_id)
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return JoinInfoResponse(
        id=info.meeting.id,
        title=info.meeting.title,
        meeting_type=info.meeting.meeting_type,
        status=info.meeting.status,
        scheduled_start_at=info.meeting.scheduled_start_at,
        requires_password=info.requires_password,
        joinable_now=info.joinable_now,
        room_phase=info.room_phase,
        live_deadline_at=info.live_deadline_at,
        waiting_room_enabled=info.meeting.waiting_room_enabled,
        locked=info.meeting.locked_at is not None,
    )


@router.post("/{meeting_id}/join", response_model=JoinMeetingResponse)
async def join_meeting(
    meeting_id: uuid.UUID,
    body: JoinMeetingRequest,
    user: CurrentUserDep,
    service: MeetingServiceDep,
) -> JoinMeetingResponse:
    try:
        result = await service.join(meeting_id=meeting_id, user=user, password=body.password)
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return _join_response(result)


@router.post("/{meeting_id}/guest-join", response_model=JoinMeetingResponse)
async def guest_join_meeting(
    meeting_id: uuid.UUID, body: GuestJoinMeetingRequest, service: MeetingServiceDep
) -> JoinMeetingResponse:
    """§35 — deliberately no CurrentUserDep: a guest has no DITSALA account."""
    try:
        result = await service.guest_join(
            meeting_id=meeting_id,
            guest_display_name=body.guest_display_name,
            password=body.password,
            guest_email=body.guest_email,
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return _join_response(result)


@router.post("/{meeting_id}/host-link", response_model=MeetHostLinkResponse)
async def create_host_link(
    meeting_id: uuid.UUID, user: CurrentUserDep, settings: SettingsDep, service: MeetingServiceDep
) -> MeetHostLinkResponse:
    """Mints a short-lived, meeting-scoped token (§9) so the mobile app can
    hand a host off into `apps/meet` — a separate origin with no session of
    its own — without putting the real access token in a URL."""
    try:
        await service.assert_host_or_cohost(meeting_id, user.id)
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    token = create_meet_host_token(meeting_id, user.id, jwt_secret=settings.jwt_secret)
    return MeetHostLinkResponse(token=token)


@router.post("/{meeting_id}/host-join", response_model=JoinMeetingResponse)
async def host_join_meeting(
    meeting_id: uuid.UUID,
    body: MeetHostJoinRequest,
    settings: SettingsDep,
    session: SessionDep,
    service: MeetingServiceDep,
) -> JoinMeetingResponse:
    """Public — the token itself, not a header, is the credential (mirrors
    `get_participant_status`'s "public by design" reasoning): a host opening
    their meeting from `apps/meet` has no session on that origin yet."""
    try:
        token_meeting_id, user_id = decode_meet_host_token(
            body.token, jwt_secret=settings.jwt_secret
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired link.") from exc
    if token_meeting_id != meeting_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This link isn't valid for this meeting.")
    user = await UserRepository(session).get(user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired link.")
    try:
        result = await service.join(meeting_id=meeting_id, user=user, password=None)
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return _join_response(result)


@router.post("/{meeting_id}/host-pin-join", response_model=JoinMeetingResponse)
async def host_pin_join(
    meeting_id: uuid.UUID, body: HostPinJoinRequest, service: MeetingServiceDep
) -> JoinMeetingResponse:
    """Public — the PIN itself is the credential, same reasoning as
    `host_join_meeting` above. See `MeetingService.host_pin_join`'s
    docstring, including its one disclosed limitation."""
    try:
        result = await service.host_pin_join(meeting_id=meeting_id, pin=body.pin)
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return _join_response(result)


@router.get(
    "/{meeting_id}/participants/{participant_id}/status", response_model=JoinMeetingResponse
)
async def get_participant_status(
    meeting_id: uuid.UUID, participant_id: uuid.UUID, service: MeetingServiceDep
) -> JoinMeetingResponse:
    """Public — see `MeetingService.get_participant_status`'s docstring
    for why this is safe without auth. Lets a waiting-room client poll
    for admission using the participant id it already has."""
    try:
        result = await service.get_participant_status(
            meeting_id=meeting_id, participant_id=participant_id
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return _join_response(result)


@router.post("/{meeting_id}/leave", status_code=204)
async def leave_meeting(
    meeting_id: uuid.UUID, user: CurrentUserDep, service: MeetingServiceDep
) -> None:
    await service.leave(meeting_id=meeting_id, user_id=user.id)


@router.post("/{meeting_id}/participants/{participant_id}/leave", status_code=204)
async def participant_leave(
    meeting_id: uuid.UUID, participant_id: uuid.UUID, service: MeetingServiceDep
) -> None:
    """Public given a valid participant_id — the guest counterpart to
    `leave_meeting` above (guests have no JWT, so they can never be
    resolved by `user_id`). See `MeetingService.mark_participant_left`'s
    docstring for why this matters beyond just bookkeeping accuracy."""
    try:
        await service.mark_participant_left(meeting_id=meeting_id, participant_id=participant_id)
    except MeetingError as exc:
        raise _as_http_error(exc) from exc


@router.post("/{meeting_id}/end", response_model=MeetingResponse)
async def end_meeting(
    meeting_id: uuid.UUID, acting_user_id: MeetingActorDep, service: MeetingServiceDep
) -> MeetingResponse:
    """Host-only, via either a real access token or the meet-host token —
    same reasoning as recording/waiting-room/extend: a host ending their
    own live meeting from apps/meet (an "End for everyone" button) only
    ever has one of those two credentials, never a `CurrentUserDep`
    session."""
    try:
        meeting = await service.end_meeting(meeting_id=meeting_id, acting_user_id=acting_user_id)
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return MeetingResponse.model_validate(meeting)


@router.post("/{meeting_id}/extend", response_model=MeetingResponse)
async def extend_meeting(
    meeting_id: uuid.UUID,
    body: ExtendMeetingRequest,
    acting_user_id: MeetingActorDep,
    service: MeetingServiceDep,
) -> MeetingResponse:
    try:
        meeting = await service.extend_duration(
            meeting_id=meeting_id,
            acting_user_id=acting_user_id,
            additional_minutes=body.additional_minutes,
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return MeetingResponse.model_validate(meeting)


@router.delete("/{meeting_id}", status_code=204)
async def delete_meeting(
    meeting_id: uuid.UUID, user: CurrentUserDep, service: MeetingServiceDep
) -> None:
    try:
        await service.delete_meeting(meeting_id=meeting_id, acting_user_id=user.id)
    except MeetingError as exc:
        raise _as_http_error(exc) from exc


@router.post("/{meeting_id}/co-host", response_model=ParticipantResponse, status_code=201)
async def invite_co_host(
    meeting_id: uuid.UUID,
    body: InviteCoHostRequest,
    acting_user_id: MeetingActorDep,
    service: MeetingServiceDep,
) -> ParticipantResponse:
    try:
        participant = await service.invite_co_host(
            meeting_id=meeting_id, acting_user_id=acting_user_id, invitee_phone=body.phone
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return ParticipantResponse.model_validate(participant)


# ---- Phase 2: waiting room --------------------------------------------------


@router.get("/{meeting_id}/waiting-room", response_model=list[ParticipantResponse])
async def list_waiting_participants(
    meeting_id: uuid.UUID, acting_user_id: MeetingActorDep, service: MeetingServiceDep
) -> list[ParticipantResponse]:
    """Host-only, via either a real access token or the meet-host token —
    same reasoning as recording/document management (`MeetingActorDep`'s
    docstring): apps/meet's web client only ever has one of those two,
    never a `CurrentUserDep`-style session of its own."""
    try:
        waiting = await service.list_waiting_participants(
            meeting_id=meeting_id, acting_user_id=acting_user_id
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return [ParticipantResponse.model_validate(p) for p in waiting]


@router.get("/{meeting_id}/participants", response_model=list[ParticipantResponse])
async def list_participants(
    meeting_id: uuid.UUID, acting_user_id: MeetingActorDep, service: MeetingServiceDep
) -> list[ParticipantResponse]:
    """Host-only — every participant regardless of admission status, for
    a moderation panel (mute/remove/promote). See
    `MeetingService.list_participants`'s docstring for why this is a
    separate endpoint from `/waiting-room`."""
    try:
        participants = await service.list_participants(
            meeting_id=meeting_id, acting_user_id=acting_user_id
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return [ParticipantResponse.model_validate(p) for p in participants]


@router.post(
    "/{meeting_id}/participants/{participant_id}/admit", response_model=ParticipantResponse
)
async def admit_participant(
    meeting_id: uuid.UUID,
    participant_id: uuid.UUID,
    acting_user_id: MeetingActorDep,
    service: MeetingServiceDep,
) -> ParticipantResponse:
    try:
        participant = await service.admit_participant(
            meeting_id=meeting_id, acting_user_id=acting_user_id, participant_id=participant_id
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return ParticipantResponse.model_validate(participant)


# ---- Phase 2: host / co-host controls ---------------------------------------


@router.post("/{meeting_id}/participants/{participant_id}/remove", status_code=204)
async def remove_participant(
    meeting_id: uuid.UUID,
    participant_id: uuid.UUID,
    acting_user_id: MeetingActorDep,
    service: MeetingServiceDep,
) -> None:
    try:
        await service.remove_participant(
            meeting_id=meeting_id, acting_user_id=acting_user_id, participant_id=participant_id
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc


@router.post(
    "/{meeting_id}/participants/{participant_id}/promote", response_model=ParticipantResponse
)
async def promote_co_host(
    meeting_id: uuid.UUID,
    participant_id: uuid.UUID,
    acting_user_id: MeetingActorDep,
    service: MeetingServiceDep,
) -> ParticipantResponse:
    try:
        participant = await service.promote_co_host(
            meeting_id=meeting_id, acting_user_id=acting_user_id, participant_id=participant_id
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return ParticipantResponse.model_validate(participant)


@router.post("/{meeting_id}/participants/{participant_id}/mute", status_code=204)
async def mute_participant(
    meeting_id: uuid.UUID,
    participant_id: uuid.UUID,
    body: MuteParticipantRequest,
    acting_user_id: MeetingActorDep,
    service: MeetingServiceDep,
) -> None:
    try:
        await service.set_participant_muted(
            meeting_id=meeting_id,
            acting_user_id=acting_user_id,
            participant_id=participant_id,
            muted=body.muted,
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc


@router.post("/{meeting_id}/lock", response_model=MeetingResponse)
async def lock_meeting(
    meeting_id: uuid.UUID,
    body: LockMeetingRequest,
    acting_user_id: MeetingActorDep,
    service: MeetingServiceDep,
) -> MeetingResponse:
    try:
        meeting = await service.set_locked(
            meeting_id=meeting_id, acting_user_id=acting_user_id, locked=body.locked
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return MeetingResponse.model_validate(meeting)


@router.put("/{meeting_id}/waiting-room", response_model=MeetingResponse)
async def set_waiting_room(
    meeting_id: uuid.UUID,
    body: SetWaitingRoomRequest,
    acting_user_id: MeetingActorDep,
    service: MeetingServiceDep,
) -> MeetingResponse:
    """Host chooses between "hold guests until admitted" and "let them
    straight into the room to wait" — previously only settable once, at
    scheduling time. See `MeetingService.set_waiting_room_enabled`'s
    docstring."""
    try:
        meeting = await service.set_waiting_room_enabled(
            meeting_id=meeting_id, acting_user_id=acting_user_id, enabled=body.enabled
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return MeetingResponse.model_validate(meeting)


# ---- Phase 2: reactions / raise-hand -----------------------------------------


@router.post("/{meeting_id}/reactions", status_code=204)
async def send_reaction(
    meeting_id: uuid.UUID,
    body: ReactionRequest,
    service: MeetingServiceDep,
) -> None:
    """Public given a valid participant_id (`body.participant_id`) —
    every participant, guests included, can react. See
    `_public_participant`'s docstring."""
    participant = await _public_participant(meeting_id, body.participant_id, service)
    await service.send_reaction(
        meeting_id=meeting_id, participant=participant, reaction=body.reaction
    )


@router.post("/{meeting_id}/raise-hand", status_code=204)
async def raise_hand(
    meeting_id: uuid.UUID,
    body: RaiseHandRequest,
    service: MeetingServiceDep,
) -> None:
    """Public given a valid participant_id — same reasoning as `send_reaction`."""
    participant = await _public_participant(meeting_id, body.participant_id, service)
    await service.set_hand_raised(
        meeting_id=meeting_id, participant=participant, raised=body.raised
    )


# ---- Phase 2: recording -------------------------------------------------------
# Recording is authenticated via MeetingActorDep, not CurrentUserDep directly
# — it accepts either a real access token or the short-lived meet-host token
# (see `get_meeting_actor`), since apps/meet has no session of its own.


@router.post("/{meeting_id}/recordings/start", response_model=RecordingResponse)
async def start_recording(
    meeting_id: uuid.UUID, acting_user_id: MeetingActorDep, service: MeetingServiceDep
) -> RecordingResponse:
    try:
        recording = await service.start_recording(
            meeting_id=meeting_id, acting_user_id=acting_user_id
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return RecordingResponse.model_validate(recording)


@router.post("/{meeting_id}/recordings/{recording_id}/stop", response_model=RecordingResponse)
async def stop_recording(
    meeting_id: uuid.UUID,
    recording_id: uuid.UUID,
    acting_user_id: MeetingActorDep,
    service: MeetingServiceDep,
) -> RecordingResponse:
    try:
        recording = await service.stop_recording(
            meeting_id=meeting_id, acting_user_id=acting_user_id, recording_id=recording_id
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return RecordingResponse.model_validate(recording)


@router.get("/{meeting_id}/recordings", response_model=list[RecordingResponse])
async def list_recordings(
    meeting_id: uuid.UUID, acting_user_id: MeetingActorDep, service: MeetingServiceDep
) -> list[RecordingResponse]:
    try:
        recordings = await service.list_recordings(
            meeting_id=meeting_id, acting_user_id=acting_user_id
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return [RecordingResponse.model_validate(r) for r in recordings]


# ---- Meeting documents — host/co-host share files, every participant
# (including guests) can view them ----------------------------------------


@router.post("/{meeting_id}/documents/upload", response_model=MeetingDocumentUploadResponse)
async def request_document_upload(
    meeting_id: uuid.UUID,
    body: RequestDocumentUploadRequest,
    acting_user_id: MeetingActorDep,
    service: MeetingServiceDep,
) -> MeetingDocumentUploadResponse:
    try:
        document, upload_url = await service.request_document_upload(
            meeting_id=meeting_id,
            acting_user_id=acting_user_id,
            filename=body.filename,
            content_type=body.content_type,
            size_bytes=body.size_bytes,
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return MeetingDocumentUploadResponse(document_id=document.id, upload_url=upload_url)


@router.get("/{meeting_id}/documents", response_model=list[MeetingDocumentResponse])
async def list_documents(
    meeting_id: uuid.UUID, participant_id: uuid.UUID, service: MeetingServiceDep
) -> list[MeetingDocumentResponse]:
    """Public given a valid participant_id — see `MeetingService.list_documents`'s
    docstring for why this is safe without auth (guests have no JWT)."""
    try:
        documents = await service.list_documents(
            meeting_id=meeting_id, participant_id=participant_id
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return [MeetingDocumentResponse.model_validate(d) for d in documents]


@router.get(
    "/{meeting_id}/documents/{document_id}/download",
    response_model=MeetingDocumentDownloadResponse,
)
async def get_document_download_url(
    meeting_id: uuid.UUID,
    document_id: uuid.UUID,
    participant_id: uuid.UUID,
    service: MeetingServiceDep,
) -> MeetingDocumentDownloadResponse:
    try:
        url = await service.get_document_download_url(
            meeting_id=meeting_id, participant_id=participant_id, document_id=document_id
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return MeetingDocumentDownloadResponse(download_url=url)


@router.delete("/{meeting_id}/documents/{document_id}", status_code=204)
async def delete_document(
    meeting_id: uuid.UUID,
    document_id: uuid.UUID,
    acting_user_id: MeetingActorDep,
    service: MeetingServiceDep,
) -> None:
    try:
        await service.delete_document(
            meeting_id=meeting_id, acting_user_id=acting_user_id, document_id=document_id
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc


# ---- Phase 2: chat -------------------------------------------------------------


@router.post("/{meeting_id}/messages", response_model=MessageResponse, status_code=201)
async def send_message(
    meeting_id: uuid.UUID,
    body: SendMessageRequest,
    service: MeetingServiceDep,
) -> MessageResponse:
    """Public given a valid participant_id (`body.participant_id`) — a
    guest has no JWT, and this chat is meant for exactly them too."""
    sender = await _public_participant(meeting_id, body.participant_id, service)
    try:
        message = await service.send_message(
            meeting_id=meeting_id,
            sender=sender,
            body=body.body,
            recipient_participant_id=body.recipient_participant_id,
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return MessageResponse.model_validate(message)


@router.get("/{meeting_id}/messages", response_model=list[MessageResponse])
async def list_messages(
    meeting_id: uuid.UUID, participant_id: uuid.UUID, service: MeetingServiceDep
) -> list[MessageResponse]:
    """Public given a valid participant_id, same as `send_message`."""
    await _public_participant(meeting_id, participant_id, service)
    messages = await service.list_messages(meeting_id=meeting_id, participant_id=participant_id)
    return [MessageResponse.model_validate(m) for m in messages]


# ---- multilingual chat (business-model kickoff §13/§18/§20) --------------------


@router.put(
    "/{meeting_id}/participants/{participant_id}/language",
    response_model=ParticipantLanguageResponse,
)
async def set_participant_language(
    meeting_id: uuid.UUID,
    participant_id: uuid.UUID,
    body: SetParticipantLanguageRequest,
    service: MeetingServiceDep,
) -> ParticipantLanguageResponse:
    """Public given a valid participant_id — see `MeetingService`'s
    multilingual-chat section docstring for why (same trust model as
    `list_documents`/`get_participant_status`: guests have no JWT, and
    apps/meet's web client has no authenticated-user flow of its own)."""
    try:
        preference = await service.set_participant_language(
            meeting_id=meeting_id, participant_id=participant_id, language=body.language
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return ParticipantLanguageResponse.model_validate(preference)


@router.get(
    "/{meeting_id}/participants/{participant_id}/language",
    response_model=ParticipantLanguageResponse | None,
)
async def get_participant_language(
    meeting_id: uuid.UUID, participant_id: uuid.UUID, service: MeetingServiceDep
) -> ParticipantLanguageResponse | None:
    preference = await service.get_participant_language(participant_id)
    return ParticipantLanguageResponse.model_validate(preference) if preference else None


@router.post(
    "/{meeting_id}/messages/{message_id}/translate", response_model=TranslateMessageResponse
)
async def translate_message(
    meeting_id: uuid.UUID,
    message_id: uuid.UUID,
    participant_id: uuid.UUID,
    service: MeetingServiceDep,
) -> TranslateMessageResponse:
    try:
        result = await service.translate_message(
            meeting_id=meeting_id, message_id=message_id, viewer_participant_id=participant_id
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return TranslateMessageResponse(
        message_id=message_id,
        translated_text=result.translated_text,
        source_language=result.source_language,
        target_language=result.target_language,
        provider=result.provider,
        status=result.status,
        error_message=result.error_message,
    )


# ---- Phase 2: polls -------------------------------------------------------------


@router.post("/{meeting_id}/polls", response_model=PollResponse, status_code=201)
async def create_poll(
    meeting_id: uuid.UUID,
    body: CreatePollRequest,
    acting_user_id: MeetingActorDep,
    service: MeetingServiceDep,
) -> PollResponse:
    """Host/co-host only — via either a real access token or the
    meet-host token (`MeetingActorDep`), matching every other host
    action apps/meet needs to call."""
    creator = await _current_participant(meeting_id, acting_user_id, service)
    try:
        poll = await service.create_poll(
            meeting_id=meeting_id,
            acting_user_id=acting_user_id,
            creator=creator,
            question=body.question,
            options=body.options,
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return PollResponse.model_validate(poll)


@router.get("/{meeting_id}/polls", response_model=list[PollResponse])
async def list_polls(
    meeting_id: uuid.UUID, participant_id: uuid.UUID, service: MeetingServiceDep
) -> list[PollResponse]:
    """Public given a valid participant_id — any participant, guests
    included, needs to see and vote on a meeting's polls."""
    await _public_participant(meeting_id, participant_id, service)
    polls = await service.list_polls(meeting_id=meeting_id)
    return [PollResponse.model_validate(p) for p in polls]


@router.post("/{meeting_id}/polls/{poll_id}/vote", status_code=204)
async def vote_poll(
    meeting_id: uuid.UUID,
    poll_id: uuid.UUID,
    body: VotePollRequest,
    service: MeetingServiceDep,
) -> None:
    """Public given a valid participant_id (`body.participant_id`)."""
    voter = await _public_participant(meeting_id, body.participant_id, service)
    try:
        await service.vote_poll(poll_id=poll_id, voter=voter, option_index=body.option_index)
    except MeetingError as exc:
        raise _as_http_error(exc) from exc


@router.post("/{meeting_id}/polls/{poll_id}/close", response_model=PollResponse)
async def close_poll(
    meeting_id: uuid.UUID,
    poll_id: uuid.UUID,
    acting_user_id: MeetingActorDep,
    service: MeetingServiceDep,
) -> PollResponse:
    try:
        poll = await service.close_poll(
            meeting_id=meeting_id, acting_user_id=acting_user_id, poll_id=poll_id
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return PollResponse.model_validate(poll)


@router.get("/{meeting_id}/polls/{poll_id}/results", response_model=PollResultsResponse)
async def get_poll_results(
    meeting_id: uuid.UUID,
    poll_id: uuid.UUID,
    participant_id: uuid.UUID,
    service: MeetingServiceDep,
) -> PollResultsResponse:
    """Public given a valid participant_id, same as `list_polls`."""
    await _public_participant(meeting_id, participant_id, service)
    try:
        results = await service.get_poll_results(poll_id=poll_id)
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return PollResultsResponse(
        poll=PollResponse.model_validate(results.poll), counts=results.counts
    )


# ---- Phase 2: Q&A ----------------------------------------------------------------


@router.post("/{meeting_id}/questions", response_model=QuestionResponse, status_code=201)
async def ask_question(
    meeting_id: uuid.UUID,
    body: AskQuestionRequest,
    service: MeetingServiceDep,
) -> QuestionResponse:
    """Public given a valid participant_id (`body.participant_id`)."""
    asker = await _public_participant(meeting_id, body.participant_id, service)
    question = await service.ask_question(meeting_id=meeting_id, asker=asker, body=body.body)
    return QuestionResponse.model_validate(question)


@router.get("/{meeting_id}/questions", response_model=list[QuestionResponse])
async def list_questions(
    meeting_id: uuid.UUID, participant_id: uuid.UUID, service: MeetingServiceDep
) -> list[QuestionResponse]:
    """Public given a valid participant_id."""
    await _public_participant(meeting_id, participant_id, service)
    questions = await service.list_questions(meeting_id=meeting_id)
    return [QuestionResponse.model_validate(q) for q in questions]


@router.post("/{meeting_id}/questions/{question_id}/upvote", response_model=QuestionResponse)
async def upvote_question(
    meeting_id: uuid.UUID,
    question_id: uuid.UUID,
    participant_id: uuid.UUID,
    service: MeetingServiceDep,
) -> QuestionResponse:
    """Public given a valid participant_id — previously accepted any
    authenticated user regardless of meeting membership (the `_user`
    param was unused); now actually scoped to this meeting's participants."""
    await _public_participant(meeting_id, participant_id, service)
    try:
        question = await service.upvote_question(question_id=question_id)
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return QuestionResponse.model_validate(question)


@router.post("/{meeting_id}/questions/{question_id}/answer", response_model=QuestionResponse)
async def answer_question(
    meeting_id: uuid.UUID,
    question_id: uuid.UUID,
    acting_user_id: MeetingActorDep,
    service: MeetingServiceDep,
) -> QuestionResponse:
    try:
        question = await service.answer_question(
            meeting_id=meeting_id, acting_user_id=acting_user_id, question_id=question_id
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return QuestionResponse.model_validate(question)


@router.post("/{meeting_id}/questions/{question_id}/dismiss", response_model=QuestionResponse)
async def dismiss_question(
    meeting_id: uuid.UUID,
    question_id: uuid.UUID,
    acting_user_id: MeetingActorDep,
    service: MeetingServiceDep,
) -> QuestionResponse:
    try:
        question = await service.dismiss_question(
            meeting_id=meeting_id, acting_user_id=acting_user_id, question_id=question_id
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return QuestionResponse.model_validate(question)


# ---- Phase 2: breakout rooms ------------------------------------------------


@router.post(
    "/{meeting_id}/breakout-rooms", response_model=list[BreakoutRoomResponse], status_code=201
)
async def create_breakout_rooms(
    meeting_id: uuid.UUID,
    body: CreateBreakoutRoomsRequest,
    acting_user_id: MeetingActorDep,
    service: MeetingServiceDep,
) -> list[BreakoutRoomResponse]:
    try:
        rooms = await service.create_breakout_rooms(
            meeting_id=meeting_id, acting_user_id=acting_user_id, names=body.names
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return [BreakoutRoomResponse.model_validate(r) for r in rooms]


@router.get("/{meeting_id}/breakout-rooms", response_model=list[BreakoutRoomResponse])
async def list_breakout_rooms(
    meeting_id: uuid.UUID, participant_id: uuid.UUID, service: MeetingServiceDep
) -> list[BreakoutRoomResponse]:
    """Public given a valid participant_id — every participant needs to
    see which breakout room they've been assigned to."""
    await _public_participant(meeting_id, participant_id, service)
    rooms = await service.list_breakout_rooms(meeting_id=meeting_id)
    return [BreakoutRoomResponse.model_validate(r) for r in rooms]


@router.post("/{meeting_id}/breakout-rooms/{breakout_room_id}/assign", status_code=204)
async def assign_to_breakout_room(
    meeting_id: uuid.UUID,
    breakout_room_id: uuid.UUID,
    body: AssignBreakoutRoomRequest,
    acting_user_id: MeetingActorDep,
    service: MeetingServiceDep,
) -> None:
    try:
        await service.assign_to_breakout_room(
            meeting_id=meeting_id,
            acting_user_id=acting_user_id,
            breakout_room_id=breakout_room_id,
            participant_id=body.participant_id,
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc


@router.post(
    "/{meeting_id}/breakout-rooms/{breakout_room_id}/join", response_model=RoomAccessTokenResponse
)
async def join_breakout_room(
    meeting_id: uuid.UUID,
    breakout_room_id: uuid.UUID,
    participant_id: uuid.UUID,
    service: MeetingServiceDep,
) -> RoomAccessTokenResponse:
    """Public given a valid participant_id — a guest assigned to a
    breakout room has no JWT to join it with otherwise."""
    participant = await _public_participant(meeting_id, participant_id, service)
    try:
        token = await service.join_breakout_room(
            meeting_id=meeting_id, breakout_room_id=breakout_room_id, participant=participant
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return RoomAccessTokenResponse(token=token.token, livekit_url=token.livekit_url)


@router.post("/{meeting_id}/breakout-rooms/close", response_model=list[BreakoutRoomResponse])
async def close_breakout_rooms(
    meeting_id: uuid.UUID, acting_user_id: MeetingActorDep, service: MeetingServiceDep
) -> list[BreakoutRoomResponse]:
    try:
        rooms = await service.close_breakout_rooms(
            meeting_id=meeting_id, acting_user_id=acting_user_id
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return [BreakoutRoomResponse.model_validate(r) for r in rooms]


# ---- Conference Room plan feature: attendance analytics ---------------------
# Premium/Enterprise only (`conference.tools` includes "analytics") — see
# app/domain/meetings/analytics.py and app/domain/billing/conference_plans.py.


@router.get("/{meeting_id}/analytics", response_model=MeetingAnalyticsResponse)
async def get_meeting_analytics(
    meeting_id: uuid.UUID, acting_user_id: MeetingActorDep, service: MeetingServiceDep
) -> MeetingAnalyticsResponse:
    """Host/co-host only, via either a real access token or the
    meet-host token — same MeetingActorDep fix as every other in-room
    host action apps/meet needs to call (this endpoint's own first
    version, from earlier in this session, had the same CurrentUserDep
    bug every pre-existing host action had before it)."""
    try:
        report = await service.get_meeting_analytics(
            meeting_id=meeting_id, acting_user_id=acting_user_id
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return MeetingAnalyticsResponse.model_validate(report)


# ---- Phase 3: AI pipeline (transcript, notes, Q&A) --------------------------


@router.post(
    "/{meeting_id}/recordings/{recording_id}/transcribe",
    response_model=list[TranscriptSegmentResponse],
)
async def transcribe_recording(
    meeting_id: uuid.UUID,
    recording_id: uuid.UUID,
    user: CurrentUserDep,
    service: MeetingIntelligenceServiceDep,
) -> list[TranscriptSegmentResponse]:
    try:
        segments = await service.transcribe_recording(
            meeting_id=meeting_id, acting_user_id=user.id, recording_id=recording_id
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return [TranscriptSegmentResponse.model_validate(s) for s in segments]


@router.get("/{meeting_id}/transcript", response_model=list[TranscriptSegmentResponse])
async def get_transcript(
    meeting_id: uuid.UUID,
    user: CurrentUserDep,
    meeting_service: MeetingServiceDep,
    intel_service: MeetingIntelligenceServiceDep,
) -> list[TranscriptSegmentResponse]:
    await _current_participant(meeting_id, user.id, meeting_service)
    segments = await intel_service.list_transcript(meeting_id=meeting_id)
    return [TranscriptSegmentResponse.model_validate(s) for s in segments]


@router.post("/{meeting_id}/notes/generate", response_model=GeneratedNotesResponse)
async def generate_notes(
    meeting_id: uuid.UUID, user: CurrentUserDep, service: MeetingIntelligenceServiceDep
) -> GeneratedNotesResponse:
    try:
        notes = await service.generate_notes(meeting_id=meeting_id, acting_user_id=user.id)
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return GeneratedNotesResponse(
        summary=AiNoteResponse.model_validate(notes.summary),
        decisions=[AiNoteResponse.model_validate(n) for n in notes.decisions],
        action_items=[AiNoteResponse.model_validate(n) for n in notes.action_items],
        topics=[AiNoteResponse.model_validate(n) for n in notes.topics],
    )


@router.get("/{meeting_id}/notes", response_model=list[AiNoteResponse])
async def list_notes(
    meeting_id: uuid.UUID,
    user: CurrentUserDep,
    meeting_service: MeetingServiceDep,
    intel_service: MeetingIntelligenceServiceDep,
) -> list[AiNoteResponse]:
    await _current_participant(meeting_id, user.id, meeting_service)
    notes = await intel_service.list_notes(meeting_id=meeting_id)
    return [AiNoteResponse.model_validate(n) for n in notes]


@router.patch("/{meeting_id}/notes/{note_id}", response_model=AiNoteResponse)
async def edit_note(
    meeting_id: uuid.UUID,
    note_id: uuid.UUID,
    body: EditNoteRequest,
    user: CurrentUserDep,
    meeting_service: MeetingServiceDep,
    intel_service: MeetingIntelligenceServiceDep,
) -> AiNoteResponse:
    editor = await _current_participant(meeting_id, user.id, meeting_service)
    try:
        note = await intel_service.edit_note(
            meeting_id=meeting_id,
            note_id=note_id,
            editor_participant_id=editor.id,
            content=body.content,
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return AiNoteResponse.model_validate(note)


@router.post("/{meeting_id}/ask", response_model=AskQuestionAboutMeetingResponse)
async def ask_about_meeting(
    meeting_id: uuid.UUID,
    body: AskQuestionAboutMeetingRequest,
    user: CurrentUserDep,
    meeting_service: MeetingServiceDep,
    intel_service: MeetingIntelligenceServiceDep,
) -> AskQuestionAboutMeetingResponse:
    await _current_participant(meeting_id, user.id, meeting_service)
    try:
        answer = await intel_service.ask(meeting_id=meeting_id, question=body.question)
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return AskQuestionAboutMeetingResponse(answer=answer)


# ---- Phase 4: webinar stage control --------------------------------------


@router.post(
    "/{meeting_id}/participants/{participant_id}/invite-to-stage",
    response_model=ParticipantResponse,
)
async def invite_to_stage(
    meeting_id: uuid.UUID,
    participant_id: uuid.UUID,
    acting_user_id: MeetingActorDep,
    service: MeetingServiceDep,
) -> ParticipantResponse:
    try:
        participant = await service.invite_to_stage(
            meeting_id=meeting_id, acting_user_id=acting_user_id, participant_id=participant_id
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return ParticipantResponse.model_validate(participant)


@router.post(
    "/{meeting_id}/participants/{participant_id}/move-to-audience",
    response_model=ParticipantResponse,
)
async def move_to_audience(
    meeting_id: uuid.UUID,
    participant_id: uuid.UUID,
    acting_user_id: MeetingActorDep,
    service: MeetingServiceDep,
) -> ParticipantResponse:
    try:
        participant = await service.move_to_audience(
            meeting_id=meeting_id, acting_user_id=acting_user_id, participant_id=participant_id
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return ParticipantResponse.model_validate(participant)


# ---- Phase 4: webinar registration -----------------------------------------


@router.post(
    "/{meeting_id}/register", response_model=RegistrationResponse, status_code=201
)
async def register_for_meeting(
    meeting_id: uuid.UUID, body: RegisterForMeetingRequest, service: MeetingServiceDep
) -> RegistrationResponse:
    """Public — deliberately no CurrentUserDep, same reasoning as
    guest-join (§35): RSVP-ing to a webinar shouldn't require a DITSALA
    account."""
    try:
        registration = await service.register_for_meeting(
            meeting_id=meeting_id, email=body.email, display_name=body.display_name
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return RegistrationResponse.model_validate(registration)


@router.get("/{meeting_id}/registrations", response_model=list[RegistrationResponse])
async def list_registrations(
    meeting_id: uuid.UUID, user: CurrentUserDep, service: MeetingServiceDep
) -> list[RegistrationResponse]:
    try:
        registrations = await service.list_registrations(
            meeting_id=meeting_id, acting_user_id=user.id
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return [RegistrationResponse.model_validate(r) for r in registrations]
