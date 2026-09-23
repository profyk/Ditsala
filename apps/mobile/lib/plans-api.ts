/**
 * Backend API client for the public /plans routes (backend/app/api/v1/
 * routers/plans.py) — backs the Conference Room screen's plan/tools
 * comparison with real, admin-configured plans/prices/entitlements
 * rather than a hardcoded feature table.
 */

import { request } from "./api";

export interface PlanPrice {
  id: string;
  currency: string;
  amount_cents: number;
  billing_interval: "month" | "year" | "one_time";
  status: "active" | "archived";
  effective_from: string;
  effective_until: string | null;
}

export interface PlanEntitlement {
  key: string;
  value: unknown;
}

export interface Plan {
  id: string;
  code: string;
  product: "free" | "vip" | "business" | "conference";
  name: string;
  prices: PlanPrice[];
  entitlements: PlanEntitlement[];
}

export const plansApi = {
  list: (accessToken: string) => request<Plan[]>("/plans", { method: "GET", token: accessToken }),

  mine: (accessToken: string) =>
    request<{ plan_code: string }>("/plans/me", { method: "GET", token: accessToken }),
};

/** `amount_cents` + `currency` -> "R199.00" / "$19.99" — no i18n library,
 * matching this app's existing "avoid a new dependency" convention; falls
 * back to a plain currency-code prefix if `Intl` can't format it. */
export function formatPrice(price: PlanPrice): string {
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: price.currency,
    }).format(price.amount_cents / 100);
  } catch {
    return `${price.currency} ${(price.amount_cents / 100).toFixed(2)}`;
  }
}
