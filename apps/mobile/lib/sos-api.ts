/**
 * Backend API client for SOS / emergency escalation
 * (docs/DITSALA_MASTER_SPEC.md §26). See `app/sos/index.tsx` for the
 * offline-safe retry queue wrapped around `trigger` — a dropped network
 * request must never silently swallow an SOS trigger.
 */

import { request } from "./api";

export type SosStatus = "armed" | "cancelled" | "escalated" | "resolved";

export interface SosEvent {
  id: string;
  triggered_at: string;
  cancel_window_seconds: number;
  cancelled_at: string | null;
  status: SosStatus;
}

export interface SosNotification {
  notified_user_id: string;
  notified_at: string;
  channel: "push" | "sms";
}

export const sosApi = {
  trigger: (accessToken: string, lastKnownLocationRef?: string) =>
    request<SosEvent>("/sos/trigger", {
      token: accessToken,
      body: { last_known_location_ref: lastKnownLocationRef ?? null },
    }),

  cancel: (accessToken: string, eventId: string) =>
    request<SosEvent>(`/sos/${eventId}/cancel`, { method: "POST", token: accessToken }),

  escalate: (accessToken: string, eventId: string) =>
    request<SosEvent>(`/sos/${eventId}/escalate`, { method: "POST", token: accessToken }),

  listEvents: (accessToken: string) =>
    request<SosEvent[]>("/sos", { method: "GET", token: accessToken }),

  listNotifications: (accessToken: string, eventId: string) =>
    request<SosNotification[]>(`/sos/${eventId}/notifications`, {
      method: "GET",
      token: accessToken,
    }),
};
