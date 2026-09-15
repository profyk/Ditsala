/**
 * Backend API client for Circle — contact requests, trust tiers,
 * invitations, block & report (docs/DITSALA_MASTER_SPEC.md §22-24). No
 * native-crypto blocker here (unlike messaging), so this backs a real UI.
 */

import { request } from "./api";

export type ContactTier = "unverified" | "verified" | "trusted" | "blocked";
export type ContactRequestChannel = "qr" | "invite_link" | "phone_match";
export type ContactRequestStatus = "pending" | "accepted" | "declined";

export interface ContactRequest {
  id: string;
  from_user_id: string;
  to_user_id: string;
  status: ContactRequestStatus;
  channel: ContactRequestChannel;
  created_at: string;
}

export interface ContactRequestListItem extends ContactRequest {
  from_user_display_name: string;
  to_user_display_name: string;
}

export interface Contact {
  id: string;
  contact_user_id: string;
  contact_display_name: string;
  tier: ContactTier;
  safety_number_verified_at: string | null;
}

export interface Report {
  id: string;
  reported_user_id: string;
  status: "open" | "reviewed" | "actioned";
}

export interface Invitation {
  id: string;
  invite_code: string;
  channel: "sms" | "link";
  status: "sent" | "redeemed" | "expired";
  expires_at: string;
}

export const circleApi = {
  // --- §22: contact requests ---

  sendContactRequest: (accessToken: string, toUserId: string, channel: ContactRequestChannel) =>
    request<ContactRequest>("/circle/requests", {
      token: accessToken,
      body: { to_user_id: toUserId, channel },
    }),

  acceptContactRequest: (accessToken: string, requestId: string) =>
    request<ContactRequest>(`/circle/requests/${requestId}/accept`, {
      method: "POST",
      token: accessToken,
    }),

  declineContactRequest: (accessToken: string, requestId: string) =>
    request<ContactRequest>(`/circle/requests/${requestId}/decline`, {
      method: "POST",
      token: accessToken,
    }),

  listIncomingRequests: (accessToken: string) =>
    request<ContactRequestListItem[]>("/circle/requests/incoming", {
      method: "GET",
      token: accessToken,
    }),

  listOutgoingRequests: (accessToken: string) =>
    request<ContactRequestListItem[]>("/circle/requests/outgoing", {
      method: "GET",
      token: accessToken,
    }),

  // --- §22-23: contacts & trust tiers ---

  listContacts: (accessToken: string) =>
    request<Contact[]>("/circle/contacts", { method: "GET", token: accessToken }),

  listCircle: (accessToken: string) =>
    request<Contact[]>("/circle", { method: "GET", token: accessToken }),

  verifySafetyNumber: (accessToken: string, contactUserId: string) =>
    request<Contact>("/circle/safety-number/verify", {
      token: accessToken,
      body: { contact_user_id: contactUserId },
    }),

  // --- §24: block & report ---

  blockUser: (accessToken: string, targetUserId: string, reason?: string) =>
    request<void>(`/circle/block/${targetUserId}`, {
      token: accessToken,
      body: { reason: reason ?? null },
    }),

  unblockUser: (accessToken: string, targetUserId: string) =>
    request<void>(`/circle/block/${targetUserId}`, { method: "DELETE", token: accessToken }),

  reportUser: (
    accessToken: string,
    payload: { reportedUserId: string; reason: string; contextRef?: string }
  ) =>
    request<Report>("/circle/report", {
      token: accessToken,
      body: {
        reported_user_id: payload.reportedUserId,
        reason: payload.reason,
        context_ref: payload.contextRef ?? null,
      },
    }),

  // --- §22: invitations ---

  createInvitation: (accessToken: string, channel: "sms" | "link") =>
    request<Invitation>("/circle/invitations", { token: accessToken, body: { channel } }),
};
