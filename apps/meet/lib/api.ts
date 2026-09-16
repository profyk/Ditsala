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
  access: RoomAccessTokenResponse;
}

export const meetingsApi = {
  get: (meetingId: string, accessToken: string) =>
    request<MeetingResponse>(`/meetings/${meetingId}`, { method: "GET", token: accessToken }),

  join: (meetingId: string, accessToken: string, password?: string) =>
    request<JoinMeetingResponse>(`/meetings/${meetingId}/join`, {
      token: accessToken,
      body: { password: password ?? null },
    }),

  guestJoin: (meetingId: string, guestDisplayName: string, password?: string) =>
    request<JoinMeetingResponse>(`/meetings/${meetingId}/guest-join`, {
      body: { guest_display_name: guestDisplayName, password: password ?? null },
    }),
};
