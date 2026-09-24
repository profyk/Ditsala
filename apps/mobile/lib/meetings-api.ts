/**
 * Backend API client for Ditsala Meet's meeting-lifecycle endpoints
 * (docs/DITSALA_MEET_SPEC.md §4, §9) — scheduling, from the DITSALA
 * mobile app rather than the meet web app itself, per this phase's
 * explicit product decision: a member schedules a call here, sets a
 * password, and shares the resulting `meet.ditsala.app` link.
 */

import { request } from "./api";

export const MEET_WEB_BASE_URL =
  process.env.EXPO_PUBLIC_MEET_WEB_BASE_URL ?? "https://ditsala-meet.vercel.app";

export type MeetingType =
  | "standard"
  | "webinar"
  | "classroom"
  | "interview"
  | "town_hall"
  | "conference";

export interface MeetingResponse {
  id: string;
  host_user_id: string;
  title: string;
  meeting_type: MeetingType;
  status: string;
  scheduled_start_at: string | null;
  scheduled_duration_minutes: number | null;
  waiting_room_enabled: boolean;
  created_at: string;
  // Only ever set on the create-meeting response — a same-tab, same-
  // origin alternative to the fragile mobile-to-apps/meet host-link
  // handoff. Anyone with it (host or a co-host) authenticates as the
  // host directly on the meeting page itself, no navigation needed.
  host_pin?: string | null;
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

export interface MyRecordingResponse extends RecordingResponse {
  meeting_title: string;
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

export interface MyMeetingDocumentResponse extends MeetingDocumentResponse {
  meeting_title: string;
}

export interface CreateMeetingPayload {
  title: string;
  meeting_type?: MeetingType;
  scheduled_start_at: string | null; // ISO 8601, UTC
  scheduled_duration_minutes?: number | null;
  password: string;
  waiting_room_enabled?: boolean;
}

export const meetingsApi = {
  create: (accessToken: string, payload: CreateMeetingPayload) =>
    request<MeetingResponse>("/meetings", { token: accessToken, body: payload }),

  list: (accessToken: string) =>
    request<MeetingResponse[]>("/meetings", { method: "GET", token: accessToken }),

  // Mints the short-lived meet-host token (backend/app/core/security.py's
  // create_meet_host_token) that lets "My Meetings" open a scheduled
  // meeting directly into the Ditsala Meet web app as its host, instead of
  // the guest-join form.
  hostJoinLink: (accessToken: string, meetingId: string) =>
    request<{ token: string }>(`/meetings/${meetingId}/host-link`, {
      method: "POST",
      token: accessToken,
    }),

  delete: (accessToken: string, meetingId: string) =>
    request<void>(`/meetings/${meetingId}`, { method: "DELETE", token: accessToken }),

  inviteCoHost: (accessToken: string, meetingId: string, phone: string) =>
    request<{ id: string; role: string }>(`/meetings/${meetingId}/co-host`, {
      token: accessToken,
      body: { phone },
    }),

  // "My Recordings" — every recording/document across every meeting this
  // user hosts, not scoped to one meeting.
  myRecordings: (accessToken: string) =>
    request<MyRecordingResponse[]>("/meetings/recordings/mine", {
      method: "GET",
      token: accessToken,
    }),

  myDocuments: (accessToken: string) =>
    request<MyMeetingDocumentResponse[]>("/meetings/documents/mine", {
      method: "GET",
      token: accessToken,
    }),

  recordingDownloadUrl: (accessToken: string, meetingId: string, recordingId: string) =>
    request<{ download_url: string }>(
      `/meetings/${meetingId}/recordings/${recordingId}/download`,
      { method: "GET", token: accessToken }
    ),

  deleteRecording: (accessToken: string, meetingId: string, recordingId: string) =>
    request<void>(`/meetings/${meetingId}/recordings/${recordingId}`, {
      method: "DELETE",
      token: accessToken,
    }),

  documentDownloadUrl: (accessToken: string, meetingId: string, documentId: string) =>
    request<{ download_url: string }>(
      `/meetings/${meetingId}/documents/${documentId}/host-download`,
      { method: "GET", token: accessToken }
    ),

  deleteDocument: (accessToken: string, meetingId: string, documentId: string) =>
    request<void>(`/meetings/${meetingId}/documents/${documentId}`, {
      method: "DELETE",
      token: accessToken,
    }),
};

export function meetingJoinLink(meetingId: string): string {
  return `${MEET_WEB_BASE_URL}/${meetingId}`;
}
