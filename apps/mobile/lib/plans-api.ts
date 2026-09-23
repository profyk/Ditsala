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

  // The Conference Room's own plan axis (Free/Pro/Premium/Enterprise) —
  // separate from `mine` above, which resolves the messaging-app
  // free/vip split. See backend app/domain/billing/conference_plans.py.
  mineConference: (accessToken: string) =>
    request<{ plan_code: string }>("/plans/me/conference", {
      method: "GET",
      token: accessToken,
    }),
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

// Human labels for the namespaced Conference Room entitlement keys
// (backend app/domain/billing/conference_plans.py) — everything else
// (VIP/free-tier entitlements) falls back to a generic label/value line,
// since this screen renders whatever entitlements a plan actually has
// rather than assuming every plan uses the Conference vocabulary.
const CONFERENCE_ENTITLEMENT_LABELS: Record<string, string> = {
  "conference.max_participants": "guests per meeting",
  "conference.max_duration_minutes": "minutes per meeting",
  "conference.max_meetings_per_month": "meetings per month",
};

const CONFERENCE_TOOL_LABELS: Record<string, string> = {
  translation: "Multilingual translation",
  polls_qna: "Polls & Q&A",
  recording: "Cloud recording",
  transcription: "Transcription",
  ai_notes: "AI meeting notes",
  breakout_rooms: "Breakout rooms",
  webinar_registration: "Webinar registration",
  analytics: "Attendance analytics",
  priority_support: "Priority support",
};

/** One readable line per entitlement — `null` reads as "Unlimited",
 * `conference.tools` (a string array) expands to one comma-joined line
 * of friendly tool names, and anything else falls back to a generic
 * "key: value" rendering so an unrecognized/future entitlement never
 * disappears from the screen. */
export function formatEntitlement(entitlement: PlanEntitlement): string {
  const { key, value } = entitlement;

  if (key === "conference.tools" && Array.isArray(value)) {
    return (value as string[]).map((id) => CONFERENCE_TOOL_LABELS[id] ?? id).join(" · ");
  }

  const label = CONFERENCE_ENTITLEMENT_LABELS[key];
  if (label) {
    return value === null || value === undefined ? `Unlimited ${label}` : `${value} ${label}`;
  }

  const fallbackLabel = key.replace(/[._]/g, " ");
  if (value === true) return fallbackLabel;
  if (value === false) return `No ${fallbackLabel}`;
  return `${fallbackLabel}: ${String(value)}`;
}
