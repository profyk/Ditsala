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

// Conference Room's own plan axis (Free/Pro/Premium/Enterprise) — a
// separate self-serve Stitch flow from VIP above, same "real payment,
// no shortcuts" reasoning.
export interface ConferencePlanUpgradeInitiationResponse {
  // Null exactly when the target plan was free — applied immediately,
  // nothing to pay or redirect for.
  payment_url: string | null;
  external_reference: string | null;
  plan_code: string;
}

export interface ConferencePlanPurchaseStatus {
  plan_code: string;
  status: "pending_payment" | "paid" | "failed";
  amount_cents: number;
  currency: string;
  paid_at: string | null;
}

export const billingApi = {
  startUpgrade: (accessToken: string, payload: VipUpgradeStartPayload) =>
    request<VipUpgradeInitiationResponse>("/account/vip/upgrade/start", {
      token: accessToken,
      body: payload,
    }),

  startConferencePlanUpgrade: (accessToken: string, planCode: string) =>
    request<ConferencePlanUpgradeInitiationResponse>("/account/conference-plan/upgrade/start", {
      token: accessToken,
      body: { plan_code: planCode },
    }),

  conferencePlanUpgradeStatus: (accessToken: string) =>
    request<ConferencePlanPurchaseStatus | null>("/account/conference-plan/upgrade/status", {
      method: "GET",
      token: accessToken,
    }),
};
