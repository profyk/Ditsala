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
};

export function meetingJoinLink(meetingId: string): string {
  return `${MEET_WEB_BASE_URL}/${meetingId}`;
}
