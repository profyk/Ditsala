/**
 * Backend API client for Ditsala Meet — docs/DITSALA_MEET_SPEC.md §4.
 * Talks to the *existing* DITSALA FastAPI backend (new /meetings routes
 * on it, not a separate service) — see the spec's §8 reuse audit for why.
 */

const BASE_URL = process.env.NEXT_PUBLIC_MEET_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number
  ) {
    super(message);
  }
}

async function request<T>(
  path: string,
  options: { method?: string; body?: unknown; token?: string } = {}
): Promise<T> {
  const response = await fetch(`${BASE_URL}/api/v1${path}`, {
    method: options.method ?? (options.body === undefined ? "GET" : "POST"),
    headers: {
      "Content-Type": "application/json",
      ...(options.token ? { Authorization: `Bearer ${options.token}` } : {}),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body?.detail === "string" ? body.detail : "Something went wrong.";
    throw new ApiError(detail, response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export interface MeetingResponse {
  id: string;
  host_user_id: string;
  livekit_room_name: string;
  title: string;
  meeting_type: string;
  status: string;
  waiting_room_enabled: boolean;
  locked_at: string | null;
}

export interface RoomAccessTokenResponse {
  token: string;
  livekit_url: string;
}

export interface JoinMeetingResponse {
  meeting: MeetingResponse;
  participant_id: string;
  role: string;
  admission_status: "waiting" | "admitted" | "removed";
  // Null while `admission_status === "waiting"` — no LiveKit token is
  // minted until a host/co-host admits this participant (§9 Phase 2).
  access: RoomAccessTokenResponse | null;
}

export interface JoinInfoResponse {
  id: string;
  title: string;
  meeting_type: string;
  status: string;
  scheduled_start_at: string | null;
  requires_password: boolean;
  joinable_now: boolean;
  room_phase: "scheduled" | "prep" | "live" | "ended";
  live_deadline_at: string | null;
}

export interface ParticipantResponse {
  id: string;
  meeting_id: string;
  user_id: string | null;
  guest_display_name: string | null;
  role: string;
  admission_status: "waiting" | "admitted" | "removed";
  stage_status: string;
  joined_at: string | null;
  left_at: string | null;
}

export interface RecordingResponse {
  id: string;
  meeting_id: string;
  egress_id: string;
  storage_key: string | null;
  duration_seconds: number | null;
  status: "processing" | "ready" | "failed";
  started_at: string | null;
  ended_at: string | null;
}

export interface MeetingDocumentResponse {
  id: string;
  meeting_id: string;
  uploaded_by_participant_id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  created_at: string;
}

export const meetingsApi = {
  get: (meetingId: string, accessToken: string) =>
    request<MeetingResponse>(`/meetings/${meetingId}`, { method: "GET", token: accessToken }),

  // Public — no auth — so a shared link's recipient can see the
  // scheduled time / password requirement before signing in or being
  // prompted for anything (§9 Phase 4).
  joinInfo: (meetingId: string) =>
    request<JoinInfoResponse>(`/meetings/${meetingId}/join-info`, { method: "GET" }),

  join: (meetingId: string, accessToken: string, password?: string) =>
    request<JoinMeetingResponse>(`/meetings/${meetingId}/join`, {
      token: accessToken,
      body: { password: password ?? null },
    }),

  guestJoin: (
    meetingId: string,
    guestDisplayName: string,
    password?: string,
    guestEmail?: string
  ) =>
    request<JoinMeetingResponse>(`/meetings/${meetingId}/guest-join`, {
      body: {
        guest_display_name: guestDisplayName,
        password: password ?? null,
        guest_email: guestEmail || null,
      },
    }),

  // Public — no auth. Lets a waiting-room client poll for admission
  // using the stable participant id it already has, instead of
  // re-calling guestJoin (which would mint a new waiting row each time).
  participantStatus: (meetingId: string, participantId: string) =>
    request<JoinMeetingResponse>(`/meetings/${meetingId}/participants/${participantId}/status`, {
      method: "GET",
    }),

  // §9 host-link handoff — apps/meet has no session of its own, so a host
  // arriving from the mobile app's "My Meetings" list authenticates here
  // with this short-lived, meeting-scoped token instead of a real access
  // token (see backend/app/core/security.py's create_meet_host_token).
  hostJoin: (meetingId: string, hostToken: string) =>
    request<JoinMeetingResponse>(`/meetings/${meetingId}/host-join`, {
      body: { token: hostToken },
    }),

  // Recording + document endpoints accept either a real access token or
  // the meet-host token as `token` — both work via MeetingActorDep on the
  // backend.
  startRecording: (meetingId: string, token: string) =>
    request<RecordingResponse>(`/meetings/${meetingId}/recordings/start`, {
      method: "POST",
      token,
    }),

  stopRecording: (meetingId: string, recordingId: string, token: string) =>
    request<RecordingResponse>(`/meetings/${meetingId}/recordings/${recordingId}/stop`, {
      method: "POST",
      token,
    }),

  listRecordings: (meetingId: string, token: string) =>
    request<RecordingResponse[]>(`/meetings/${meetingId}/recordings`, {
      method: "GET",
      token,
    }),

  requestDocumentUpload: (
    meetingId: string,
    token: string,
    file: { filename: string; content_type: string; size_bytes: number }
  ) =>
    request<{ document_id: string; upload_url: string }>(`/meetings/${meetingId}/documents/upload`, {
      token,
      body: file,
    }),

  // Public given a valid participant_id — guests have no DITSALA account
  // or JWT, so this is how they see documents shared in a meeting they're
  // actually in (see MeetingService.list_documents's docstring).
  listDocuments: (meetingId: string, participantId: string) =>
    request<MeetingDocumentResponse[]>(
      `/meetings/${meetingId}/documents?participant_id=${participantId}`,
      { method: "GET" }
    ),

  documentDownloadUrl: (meetingId: string, documentId: string, participantId: string) =>
    request<{ download_url: string }>(
      `/meetings/${meetingId}/documents/${documentId}/download?participant_id=${participantId}`,
      { method: "GET" }
    ),

  deleteDocument: (meetingId: string, documentId: string, token: string) =>
    request<void>(`/meetings/${meetingId}/documents/${documentId}`, {
      method: "DELETE",
      token,
    }),

  // Conference Room (business-model kickoff prompt) — host/co-host only,
  // via the same MeetingActorDep token (real access token or meet-host
  // token) recording/documents already use.
  listWaitingRoom: (meetingId: string, token: string) =>
    request<ParticipantResponse[]>(`/meetings/${meetingId}/waiting-room`, {
      method: "GET",
      token,
    }),

  admitParticipant: (meetingId: string, participantId: string, token: string) =>
    request<ParticipantResponse>(`/meetings/${meetingId}/participants/${participantId}/admit`, {
      method: "POST",
      token,
    }),

  extendMeeting: (meetingId: string, additionalMinutes: number, token: string) =>
    request<MeetingResponse>(`/meetings/${meetingId}/extend`, {
      token,
      body: { additional_minutes: additionalMinutes },
    }),
};

/** PUTs a File directly to a presigned storage URL — same client-side
 * upload pattern messaging media already uses, just for meeting documents. */
export async function uploadFileToPresignedUrl(uploadUrl: string, file: File): Promise<void> {
  const response = await fetch(uploadUrl, {
    method: "PUT",
    headers: { "Content-Type": file.type || "application/octet-stream" },
    body: file,
  });
  if (!response.ok) {
    throw new ApiError("Could not upload the file.", response.status);
  }
}
