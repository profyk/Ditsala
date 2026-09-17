/**
 * Backend API client for self-service account lifecycle
 * (docs/DITSALA_MASTER_SPEC.md §14, §34.2) — deactivation and its
 * reversal within the 30-day grace window.
 */

import { request } from "./api";

export interface AccountDeactivationStatus {
  account_state: string;
  deactivated_at: string | null;
  hard_delete_after: string | null;
}

export const accountApi = {
  deactivate: (accessToken: string) =>
    request<AccountDeactivationStatus>("/account/deactivate", { token: accessToken }),

  cancelDeactivation: (accessToken: string) =>
    request<AccountDeactivationStatus>("/account/deactivate/cancel", { token: accessToken }),

  // --- profile picture ---

  requestAvatarUpload: (accessToken: string, contentType: string) =>
    request<{ key: string; upload_url: string }>("/account/avatar/upload-url", {
      token: accessToken,
      body: { content_type: contentType },
    }),

  confirmAvatar: (accessToken: string, key: string) =>
    request<{ avatar_url: string | null }>("/account/avatar/confirm", {
      token: accessToken,
      body: { key },
    }),

  removeAvatar: (accessToken: string) =>
    request<void>("/account/avatar", { method: "DELETE", token: accessToken }),
};
