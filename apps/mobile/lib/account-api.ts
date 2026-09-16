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
};
