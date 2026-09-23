import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class CreateMeetingRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    meeting_type: str = Field(
        default="standard",
        pattern="^(standard|webinar|classroom|interview|town_hall|conference)$",
    )
    scheduled_start_at: datetime | None = None
    scheduled_duration_minutes: int | None = Field(default=None, gt=0)
    password: str | None = None
    waiting_room_enabled: bool = False
    prep_lead_minutes: int = Field(default=15, ge=0, le=180)


class MeetingResponse(BaseModel):
    id: uuid.UUID
    host_user_id: uuid.UUID
    livekit_room_name: str
    title: str
    meeting_type: str
    status: str
    scheduled_start_at: datetime | None
    scheduled_duration_minutes: int | None
    actual_start_at: datetime | None
    actual_end_at: datetime | None
    waiting_room_enabled: bool
    locked_at: datetime | None
    prep_lead_minutes: int
    duration_extended_minutes: int
    created_at: datetime
    # Only ever populated on the create_meeting response — see
    # MeetingService.create_meeting's docstring for why this is the one
    # and only moment the plaintext PIN is readable anywhere. Every other
    # response validated from a `Meeting` (list, get-by-id, etc.) leaves
    # this null; only the hash is ever persisted.
    host_pin: str | None = None

    model_config = {"from_attributes": True}


class JoinInfoResponse(BaseModel):
    """Public — never includes the password itself, only whether one is
    required (§9 Phase 4: a shared-link recipient checks this before
    authenticating or being prompted for a password)."""

    id: uuid.UUID
    title: str
    meeting_type: str
    status: str
    scheduled_start_at: datetime | None
    requires_password: bool
    joinable_now: bool
    room_phase: str
    live_deadline_at: datetime | None
    # So a UI can show the current "hold guests until admitted" vs "let
    # them straight in" setting *before* anyone has toggled it (see
    # `set_waiting_room_enabled` — this was previously not exposed
    # anywhere a host could read it back, only ever written blind).
    waiting_room_enabled: bool
    # Same reasoning for the Lock control — a reconnecting host's UI
    # shouldn't have to guess (and default-display "unlocked") before
    # the real state is known.
    locked: bool


class JoinMeetingRequest(BaseModel):
    password: str | None = None


class ExtendMeetingRequest(BaseModel):
    additional_minutes: int = Field(gt=0, le=240)


class InviteCoHostRequest(BaseModel):
    phone: str = Field(min_length=4, max_length=32)


class GuestJoinMeetingRequest(BaseModel):
    guest_display_name: str = Field(min_length=1, max_length=120)
    password: str | None = None
    # Optional — used only to best-effort mark a matching §9 Phase 4
    # registration as attended, never required to join.
    guest_email: EmailStr | None = None


class RoomAccessTokenResponse(BaseModel):
    token: str
    livekit_url: str


class JoinMeetingResponse(BaseModel):
    meeting: MeetingResponse
    participant_id: uuid.UUID
    role: str
    admission_status: str
    access: RoomAccessTokenResponse | None


class ParticipantResponse(BaseModel):
    id: uuid.UUID
    meeting_id: uuid.UUID
    user_id: uuid.UUID | None
    guest_display_name: str | None
    role: str
    admission_status: str
    stage_status: str
    joined_at: datetime | None
    left_at: datetime | None

    model_config = {"from_attributes": True}


class MuteParticipantRequest(BaseModel):
    muted: bool


class LockMeetingRequest(BaseModel):
    locked: bool


class SetWaitingRoomRequest(BaseModel):
    enabled: bool


class ReactionRequest(BaseModel):
    # Public given a valid participant_id, same trust model as
    # `list_documents`/`set_participant_language` — a guest has no JWT,
    # so the request itself carries which participant this is from.
    participant_id: uuid.UUID
    reaction: str = Field(min_length=1, max_length=32)


class RaiseHandRequest(BaseModel):
    participant_id: uuid.UUID
    raised: bool


class MeetHostLinkResponse(BaseModel):
    token: str


class MeetHostJoinRequest(BaseModel):
    token: str


class HostPinJoinRequest(BaseModel):
    pin: str = Field(min_length=1, max_length=32)


class RecordingResponse(BaseModel):
    id: uuid.UUID
    meeting_id: uuid.UUID
    egress_id: str
    storage_key: str | None
    duration_seconds: int | None
    status: str
    started_at: datetime | None
    ended_at: datetime | None

    model_config = {"from_attributes": True}


class SendMessageRequest(BaseModel):
    # Public given a valid participant_id — same reasoning as ReactionRequest.
    participant_id: uuid.UUID
    body: str = Field(min_length=1, max_length=4000)
    recipient_participant_id: uuid.UUID | None = None


class MessageResponse(BaseModel):
    id: uuid.UUID
    meeting_id: uuid.UUID
    sender_participant_id: uuid.UUID
    recipient_participant_id: uuid.UUID | None
    body: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SetParticipantLanguageRequest(BaseModel):
    language: str = Field(min_length=2, max_length=16)


class ParticipantLanguageResponse(BaseModel):
    participant_id: uuid.UUID
    language: str

    model_config = {"from_attributes": True}


class TranslateMessageResponse(BaseModel):
    message_id: uuid.UUID
    translated_text: str | None
    source_language: str | None
    target_language: str
    provider: str | None
    status: str
    error_message: str | None

    model_config = {"from_attributes": True}


class CreatePollRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    options: list[str] = Field(min_length=2, max_length=10)


class VotePollRequest(BaseModel):
    # Public given a valid participant_id — same reasoning as ReactionRequest.
    participant_id: uuid.UUID
    option_index: int = Field(ge=0)


class PollResponse(BaseModel):
    id: uuid.UUID
    meeting_id: uuid.UUID
    created_by_participant_id: uuid.UUID
    question: str
    options: list[str]
    closed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PollResultsResponse(BaseModel):
    poll: PollResponse
    counts: dict[int, int]


class AskQuestionRequest(BaseModel):
    # Public given a valid participant_id — same reasoning as ReactionRequest.
    participant_id: uuid.UUID
    body: str = Field(min_length=1, max_length=2000)


class CreateBreakoutRoomsRequest(BaseModel):
    names: list[str] = Field(min_length=1, max_length=50)


class BreakoutRoomResponse(BaseModel):
    id: uuid.UUID
    meeting_id: uuid.UUID
    name: str
    closed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AssignBreakoutRoomRequest(BaseModel):
    participant_id: uuid.UUID


# --- Meeting analytics (Premium/Enterprise Conference plans) ----------
# Response shape mirrors `app/domain/meetings/analytics.py`'s dataclasses
# exactly — see that module for what each field means and how it's computed.


class ParticipantAttendanceResponse(BaseModel):
    participant_id: uuid.UUID
    display_name: str
    role: str
    is_guest: bool
    joined_at: datetime | None
    left_at: datetime | None
    attended_seconds: int

    model_config = {"from_attributes": True}


class MeetingAnalyticsResponse(BaseModel):
    meeting_id: uuid.UUID
    as_of: datetime
    total_participant_rows: int
    unique_attendees: int
    guest_attendees: int
    total_attendance_seconds: int
    average_attendance_seconds: float
    peak_concurrent_attendees: int
    attendees: list[ParticipantAttendanceResponse]

    model_config = {"from_attributes": True}


class QuestionResponse(BaseModel):
    id: uuid.UUID
    meeting_id: uuid.UUID
    asked_by_participant_id: uuid.UUID
    body: str
    upvote_count: int
    status: str
    answered_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---- Phase 3: AI pipeline (transcript, notes, search) -----------------------


class TranscriptSegmentResponse(BaseModel):
    id: uuid.UUID
    meeting_id: uuid.UUID
    speaker_participant_id: uuid.UUID | None
    text_segment: str
    started_at_ms: int
    ended_at_ms: int

    model_config = {"from_attributes": True}


class AiNoteResponse(BaseModel):
    id: uuid.UUID
    meeting_id: uuid.UUID
    kind: str
    content: str
    edited_by_participant_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class GeneratedNotesResponse(BaseModel):
    summary: AiNoteResponse
    decisions: list[AiNoteResponse]
    action_items: list[AiNoteResponse]
    topics: list[AiNoteResponse]


class EditNoteRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class AskQuestionAboutMeetingRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class AskQuestionAboutMeetingResponse(BaseModel):
    answer: str


class MeetingSearchResultResponse(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ---- Phase 4: webinar stage control + registration --------------------------


class RegisterForMeetingRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)


class RegistrationResponse(BaseModel):
    id: uuid.UUID
    meeting_id: uuid.UUID
    email: str
    display_name: str
    attended_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---- Meeting documents (guest-viewable files) --------------------------------


class RequestDocumentUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(gt=0)


class MeetingDocumentUploadResponse(BaseModel):
    document_id: uuid.UUID
    upload_url: str


class MeetingDocumentResponse(BaseModel):
    id: uuid.UUID
    meeting_id: uuid.UUID
    uploaded_by_participant_id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime

    model_config = {"from_attributes": True}


class MeetingDocumentDownloadResponse(BaseModel):
    download_url: str
