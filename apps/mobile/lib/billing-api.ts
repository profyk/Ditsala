/**
 * Backend API client for VIP upgrade (ADR 0012, backend/app/api/v1/routers/billing.py)
 * — the real Stitch payment flow, no shortcuts.
 */

import { request } from "./api";

export interface VipUpgradeStartPayload {
  email?: string | null;
  date_of_birth?: string | null; // "YYYY-MM-DD"
  national_id?: string | null;
}

export interface VipUpgradeInitiationResponse {
  payment_url: string;
  external_reference: string;
}

export const billingApi = {
  startUpgrade: (accessToken: string, payload: VipUpgradeStartPayload) =>
    request<VipUpgradeInitiationResponse>("/account/vip/upgrade/start", {
      token: accessToken,
      body: payload,
    }),
};
