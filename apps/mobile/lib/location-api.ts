/**
 * Backend API client for location sharing (docs/DITSALA_MASTER_SPEC.md
 * §25) — off by default, `trusted`-tier Circle contacts only.
 */

import { request } from "./api";

export interface LocationShare {
  id: string;
  sharer_user_id: string;
  recipient_user_id: string;
  starts_at: string;
  expires_at: string;
  revoked_at: string | null;
}

export interface LocationPing {
  id: string;
  lat: number;
  lng: number;
  accuracy_m: number;
  recorded_at: string;
}

export interface LocationAccessLogEntry {
  accessed_by_user_id: string;
  accessed_at: string;
}

export const locationApi = {
  createShare: (accessToken: string, recipientUserId: string, durationSeconds: number) =>
    request<LocationShare>("/location/shares", {
      token: accessToken,
      body: { recipient_user_id: recipientUserId, duration_seconds: durationSeconds },
    }),

  revokeShare: (accessToken: string, shareId: string) =>
    request<void>(`/location/shares/${shareId}`, { method: "DELETE", token: accessToken }),

  listSharesByMe: (accessToken: string) =>
    request<LocationShare[]>("/location/shares/by-me", { method: "GET", token: accessToken }),

  listSharesToMe: (accessToken: string) =>
    request<LocationShare[]>("/location/shares/to-me", { method: "GET", token: accessToken }),

  recordPing: (
    accessToken: string,
    shareId: string,
    payload: { lat: number; lng: number; accuracyM: number }
  ) =>
    request<LocationPing>(`/location/shares/${shareId}/pings`, {
      token: accessToken,
      body: { lat: payload.lat, lng: payload.lng, accuracy_m: payload.accuracyM },
    }),

  listPings: (accessToken: string, shareId: string) =>
    request<LocationPing[]>(`/location/shares/${shareId}/pings`, {
      method: "GET",
      token: accessToken,
    }),

  listAccessLog: (accessToken: string, shareId: string) =>
    request<LocationAccessLogEntry[]>(`/location/shares/${shareId}/access-log`, {
      method: "GET",
      token: accessToken,
    }),
};
