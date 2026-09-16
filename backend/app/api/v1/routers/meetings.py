import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.v1.deps import CurrentUserDep, MeetingServiceDep
from app.domain.meetings.service import JoinResult, MeetingError
from app.models.meetings import MeetingParticipant
from app.schemas.meetings import (
    AskQuestionRequest,
    AssignBreakoutRoomRequest,
    BreakoutRoomResponse,
    CreateBreakoutRoomsRequest,
    CreateMeetingRequest,
    CreatePollRequest,
    GuestJoinMeetingRequest,
    JoinMeetingRequest,
    JoinMeetingResponse,
    LockMeetingRequest,
    MeetingResponse,
    MessageResponse,
    MuteParticipantRequest,
    ParticipantResponse,
    PollResponse,
    PollResultsResponse,
    QuestionResponse,
    RaiseHandRequest,
    ReactionRequest,
    RecordingResponse,
    RoomAccessTokenResponse,
    SendMessageRequest,
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
    meeting_id: uuid.UUID, user: CurrentUserDep, service: MeetingServiceDep
) -> MeetingParticipant:
    participant = await service.get_participant_for_user(meeting_id=meeting_id, user_id=user.id)
    if participant is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You are not a participant in this meeting."
        )
    return participant


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
    )
    return MeetingResponse.model_validate(meeting)


@router.get("/{meeting_id}", response_model=MeetingResponse)
async def get_meeting(
    meeting_id: uuid.UUID, _user: CurrentUserDep, service: MeetingServiceDep
) -> MeetingResponse:
    try:
        meeting = await service.get_meeting(meeting_id)
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return MeetingResponse.model_validate(meeting)


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
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return _join_response(result)


@router.post("/{meeting_id}/leave", status_code=204)
async def leave_meeting(
    meeting_id: uuid.UUID, user: CurrentUserDep, service: MeetingServiceDep
) -> None:
    await service.leave(meeting_id=meeting_id, user_id=user.id)


@router.post("/{meeting_id}/end", response_model=MeetingResponse)
async def end_meeting(
    meeting_id: uuid.UUID, user: CurrentUserDep, service: MeetingServiceDep
) -> MeetingResponse:
    try:
        meeting = await service.end_meeting(meeting_id=meeting_id, acting_user_id=user.id)
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return MeetingResponse.model_validate(meeting)


# ---- Phase 2: waiting room --------------------------------------------------


@router.get("/{meeting_id}/waiting-room", response_model=list[ParticipantResponse])
async def list_waiting_participants(
    meeting_id: uuid.UUID, user: CurrentUserDep, service: MeetingServiceDep
) -> list[ParticipantResponse]:
    try:
        waiting = await service.list_waiting_participants(
            meeting_id=meeting_id, acting_user_id=user.id
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return [ParticipantResponse.model_validate(p) for p in waiting]


@router.post(
    "/{meeting_id}/participants/{participant_id}/admit", response_model=ParticipantResponse
)
async def admit_participant(
    meeting_id: uuid.UUID,
    participant_id: uuid.UUID,
    user: CurrentUserDep,
    service: MeetingServiceDep,
) -> ParticipantResponse:
    try:
        participant = await service.admit_participant(
            meeting_id=meeting_id, acting_user_id=user.id, participant_id=participant_id
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return ParticipantResponse.model_validate(participant)


# ---- Phase 2: host / co-host controls ---------------------------------------


@router.post("/{meeting_id}/participants/{participant_id}/remove", status_code=204)
async def remove_participant(
    meeting_id: uuid.UUID,
    participant_id: uuid.UUID,
    user: CurrentUserDep,
    service: MeetingServiceDep,
) -> None:
    try:
        await service.remove_participant(
            meeting_id=meeting_id, acting_user_id=user.id, participant_id=participant_id
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc


@router.post(
    "/{meeting_id}/participants/{participant_id}/promote", response_model=ParticipantResponse
)
async def promote_co_host(
    meeting_id: uuid.UUID,
    participant_id: uuid.UUID,
    user: CurrentUserDep,
    service: MeetingServiceDep,
) -> ParticipantResponse:
    try:
        participant = await service.promote_co_host(
            meeting_id=meeting_id, acting_user_id=user.id, participant_id=participant_id
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return ParticipantResponse.model_validate(participant)


@router.post("/{meeting_id}/participants/{participant_id}/mute", status_code=204)
async def mute_participant(
    meeting_id: uuid.UUID,
    participant_id: uuid.UUID,
    body: MuteParticipantRequest,
    user: CurrentUserDep,
    service: MeetingServiceDep,
) -> None:
    try:
        await service.set_participant_muted(
            meeting_id=meeting_id,
            acting_user_id=user.id,
            participant_id=participant_id,
            muted=body.muted,
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc


@router.post("/{meeting_id}/lock", response_model=MeetingResponse)
async def lock_meeting(
    meeting_id: uuid.UUID,
    body: LockMeetingRequest,
    user: CurrentUserDep,
    service: MeetingServiceDep,
) -> MeetingResponse:
    try:
        meeting = await service.set_locked(
            meeting_id=meeting_id, acting_user_id=user.id, locked=body.locked
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return MeetingResponse.model_validate(meeting)


# ---- Phase 2: reactions / raise-hand -----------------------------------------


@router.post("/{meeting_id}/reactions", status_code=204)
async def send_reaction(
    meeting_id: uuid.UUID,
    body: ReactionRequest,
    user: CurrentUserDep,
    service: MeetingServiceDep,
) -> None:
    participant = await _current_participant(meeting_id, user, service)
    await service.send_reaction(
        meeting_id=meeting_id, participant=participant, reaction=body.reaction
    )


@router.post("/{meeting_id}/raise-hand", status_code=204)
async def raise_hand(
    meeting_id: uuid.UUID,
    body: RaiseHandRequest,
    user: CurrentUserDep,
    service: MeetingServiceDep,
) -> None:
    participant = await _current_participant(meeting_id, user, service)
    await service.set_hand_raised(
        meeting_id=meeting_id, participant=participant, raised=body.raised
    )


# ---- Phase 2: recording -------------------------------------------------------


@router.post("/{meeting_id}/recordings/start", response_model=RecordingResponse)
async def start_recording(
    meeting_id: uuid.UUID, user: CurrentUserDep, service: MeetingServiceDep
) -> RecordingResponse:
    try:
        recording = await service.start_recording(meeting_id=meeting_id, acting_user_id=user.id)
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return RecordingResponse.model_validate(recording)


@router.post("/{meeting_id}/recordings/{recording_id}/stop", response_model=RecordingResponse)
async def stop_recording(
    meeting_id: uuid.UUID,
    recording_id: uuid.UUID,
    user: CurrentUserDep,
    service: MeetingServiceDep,
) -> RecordingResponse:
    try:
        recording = await service.stop_recording(
            meeting_id=meeting_id, acting_user_id=user.id, recording_id=recording_id
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return RecordingResponse.model_validate(recording)


@router.get("/{meeting_id}/recordings", response_model=list[RecordingResponse])
async def list_recordings(
    meeting_id: uuid.UUID, user: CurrentUserDep, service: MeetingServiceDep
) -> list[RecordingResponse]:
    try:
        recordings = await service.list_recordings(meeting_id=meeting_id, acting_user_id=user.id)
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return [RecordingResponse.model_validate(r) for r in recordings]


# ---- Phase 2: chat -------------------------------------------------------------


@router.post("/{meeting_id}/messages", response_model=MessageResponse, status_code=201)
async def send_message(
    meeting_id: uuid.UUID,
    body: SendMessageRequest,
    user: CurrentUserDep,
    service: MeetingServiceDep,
) -> MessageResponse:
    sender = await _current_participant(meeting_id, user, service)
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
    meeting_id: uuid.UUID, user: CurrentUserDep, service: MeetingServiceDep
) -> list[MessageResponse]:
    participant = await _current_participant(meeting_id, user, service)
    messages = await service.list_messages(meeting_id=meeting_id, participant_id=participant.id)
    return [MessageResponse.model_validate(m) for m in messages]


# ---- Phase 2: polls -------------------------------------------------------------


@router.post("/{meeting_id}/polls", response_model=PollResponse, status_code=201)
async def create_poll(
    meeting_id: uuid.UUID,
    body: CreatePollRequest,
    user: CurrentUserDep,
    service: MeetingServiceDep,
) -> PollResponse:
    creator = await _current_participant(meeting_id, user, service)
    try:
        poll = await service.create_poll(
            meeting_id=meeting_id,
            acting_user_id=user.id,
            creator=creator,
            question=body.question,
            options=body.options,
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return PollResponse.model_validate(poll)


@router.get("/{meeting_id}/polls", response_model=list[PollResponse])
async def list_polls(
    meeting_id: uuid.UUID, _user: CurrentUserDep, service: MeetingServiceDep
) -> list[PollResponse]:
    polls = await service.list_polls(meeting_id=meeting_id)
    return [PollResponse.model_validate(p) for p in polls]


@router.post("/{meeting_id}/polls/{poll_id}/vote", status_code=204)
async def vote_poll(
    meeting_id: uuid.UUID,
    poll_id: uuid.UUID,
    body: VotePollRequest,
    user: CurrentUserDep,
    service: MeetingServiceDep,
) -> None:
    voter = await _current_participant(meeting_id, user, service)
    try:
        await service.vote_poll(poll_id=poll_id, voter=voter, option_index=body.option_index)
    except MeetingError as exc:
        raise _as_http_error(exc) from exc


@router.post("/{meeting_id}/polls/{poll_id}/close", response_model=PollResponse)
async def close_poll(
    meeting_id: uuid.UUID,
    poll_id: uuid.UUID,
    user: CurrentUserDep,
    service: MeetingServiceDep,
) -> PollResponse:
    try:
        poll = await service.close_poll(
            meeting_id=meeting_id, acting_user_id=user.id, poll_id=poll_id
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return PollResponse.model_validate(poll)


@router.get("/{meeting_id}/polls/{poll_id}/results", response_model=PollResultsResponse)
async def get_poll_results(
    meeting_id: uuid.UUID,
    poll_id: uuid.UUID,
    _user: CurrentUserDep,
    service: MeetingServiceDep,
) -> PollResultsResponse:
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
    user: CurrentUserDep,
    service: MeetingServiceDep,
) -> QuestionResponse:
    asker = await _current_participant(meeting_id, user, service)
    question = await service.ask_question(meeting_id=meeting_id, asker=asker, body=body.body)
    return QuestionResponse.model_validate(question)


@router.get("/{meeting_id}/questions", response_model=list[QuestionResponse])
async def list_questions(
    meeting_id: uuid.UUID, _user: CurrentUserDep, service: MeetingServiceDep
) -> list[QuestionResponse]:
    questions = await service.list_questions(meeting_id=meeting_id)
    return [QuestionResponse.model_validate(q) for q in questions]


@router.post("/{meeting_id}/questions/{question_id}/upvote", response_model=QuestionResponse)
async def upvote_question(
    meeting_id: uuid.UUID,
    question_id: uuid.UUID,
    _user: CurrentUserDep,
    service: MeetingServiceDep,
) -> QuestionResponse:
    try:
        question = await service.upvote_question(question_id=question_id)
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return QuestionResponse.model_validate(question)


@router.post("/{meeting_id}/questions/{question_id}/answer", response_model=QuestionResponse)
async def answer_question(
    meeting_id: uuid.UUID,
    question_id: uuid.UUID,
    user: CurrentUserDep,
    service: MeetingServiceDep,
) -> QuestionResponse:
    try:
        question = await service.answer_question(
            meeting_id=meeting_id, acting_user_id=user.id, question_id=question_id
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return QuestionResponse.model_validate(question)


@router.post("/{meeting_id}/questions/{question_id}/dismiss", response_model=QuestionResponse)
async def dismiss_question(
    meeting_id: uuid.UUID,
    question_id: uuid.UUID,
    user: CurrentUserDep,
    service: MeetingServiceDep,
) -> QuestionResponse:
    try:
        question = await service.dismiss_question(
            meeting_id=meeting_id, acting_user_id=user.id, question_id=question_id
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
    user: CurrentUserDep,
    service: MeetingServiceDep,
) -> list[BreakoutRoomResponse]:
    try:
        rooms = await service.create_breakout_rooms(
            meeting_id=meeting_id, acting_user_id=user.id, names=body.names
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return [BreakoutRoomResponse.model_validate(r) for r in rooms]


@router.get("/{meeting_id}/breakout-rooms", response_model=list[BreakoutRoomResponse])
async def list_breakout_rooms(
    meeting_id: uuid.UUID, _user: CurrentUserDep, service: MeetingServiceDep
) -> list[BreakoutRoomResponse]:
    rooms = await service.list_breakout_rooms(meeting_id=meeting_id)
    return [BreakoutRoomResponse.model_validate(r) for r in rooms]


@router.post("/{meeting_id}/breakout-rooms/{breakout_room_id}/assign", status_code=204)
async def assign_to_breakout_room(
    meeting_id: uuid.UUID,
    breakout_room_id: uuid.UUID,
    body: AssignBreakoutRoomRequest,
    user: CurrentUserDep,
    service: MeetingServiceDep,
) -> None:
    try:
        await service.assign_to_breakout_room(
            meeting_id=meeting_id,
            acting_user_id=user.id,
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
    user: CurrentUserDep,
    service: MeetingServiceDep,
) -> RoomAccessTokenResponse:
    participant = await _current_participant(meeting_id, user, service)
    try:
        token = await service.join_breakout_room(
            meeting_id=meeting_id, breakout_room_id=breakout_room_id, participant=participant
        )
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return RoomAccessTokenResponse(token=token.token, livekit_url=token.livekit_url)


@router.post("/{meeting_id}/breakout-rooms/close", response_model=list[BreakoutRoomResponse])
async def close_breakout_rooms(
    meeting_id: uuid.UUID, user: CurrentUserDep, service: MeetingServiceDep
) -> list[BreakoutRoomResponse]:
    try:
        rooms = await service.close_breakout_rooms(meeting_id=meeting_id, acting_user_id=user.id)
    except MeetingError as exc:
        raise _as_http_error(exc) from exc
    return [BreakoutRoomResponse.model_validate(r) for r in rooms]
