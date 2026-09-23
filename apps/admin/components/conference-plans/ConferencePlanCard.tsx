"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { billingApi, type Entitlement, type Plan, type PlanPrice } from "@/lib/admin-api";
import { ApiError } from "@/lib/api";
import {
  CONFERENCE_TOOLS,
  MAX_DURATION_MINUTES_KEY,
  MAX_GUESTS_KEY,
  MAX_MEETINGS_PER_MONTH_KEY,
  TOOLS_KEY,
  minutesToHoursLabel,
} from "@/lib/conference-plans";

/** Reads an entitlement's raw value from the list `list_entitlements`
 * returns — `undefined` (never set yet) is distinct from `null`
 * (explicitly unlimited); both render as "not set"/"unlimited" in the
 * read-only summary below, but only `undefined` pre-fills the edit
 * inputs empty rather than "unlimited". */
function findEntitlement(entitlements: Entitlement[], key: string): unknown {
  return entitlements.find((e) => e.key === key)?.value;
}

/** Empty string means "unlimited" (→ `null`) once saved — mirrors how
 * the backend already treats `null` as "no cap" everywhere in this schema. */
function parseLimitInput(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  const n = Number(trimmed);
  return Number.isFinite(n) && n >= 0 ? Math.round(n) : null;
}

export function ConferencePlanCard({
  plan,
  token,
  canAction,
  onChanged,
}: {
  plan: Plan;
  token: string | null;
  canAction: boolean;
  onChanged: () => void;
}) {
  const [prices, setPrices] = useState<PlanPrice[] | null>(null);
  const [entitlements, setEntitlements] = useState<Entitlement[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [maxGuests, setMaxGuests] = useState("");
  const [maxMinutes, setMaxMinutes] = useState("");
  const [maxMeetingsPerMonth, setMaxMeetingsPerMonth] = useState("");
  const [tools, setTools] = useState<Set<string>>(new Set());
  const [reason, setReason] = useState("");

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const [p, e] = await Promise.all([
        billingApi.listPlanPrices(token, plan.id),
        billingApi.listEntitlements(token, plan.id),
      ]);
      setPrices(p);
      setEntitlements(e);
      const guests = findEntitlement(e, MAX_GUESTS_KEY);
      const minutes = findEntitlement(e, MAX_DURATION_MINUTES_KEY);
      const meetings = findEntitlement(e, MAX_MEETINGS_PER_MONTH_KEY);
      const toolList = findEntitlement(e, TOOLS_KEY);
      setMaxGuests(guests === null || guests === undefined ? "" : String(guests));
      setMaxMinutes(minutes === null || minutes === undefined ? "" : String(minutes));
      setMaxMeetingsPerMonth(
        meetings === null || meetings === undefined ? "" : String(meetings)
      );
      setTools(new Set(Array.isArray(toolList) ? (toolList as string[]) : []));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load plan details.");
    }
  }, [token, plan.id]);

  useEffect(() => {
    load();
  }, [load]);

  function toggleTool(id: string) {
    setTools((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function handleSave() {
    if (!token || !reason.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await Promise.all([
        billingApi.setEntitlement(
          token,
          plan.id,
          MAX_GUESTS_KEY,
          parseLimitInput(maxGuests),
          reason.trim()
        ),
        billingApi.setEntitlement(
          token,
          plan.id,
          MAX_DURATION_MINUTES_KEY,
          parseLimitInput(maxMinutes),
          reason.trim()
        ),
        billingApi.setEntitlement(
          token,
          plan.id,
          MAX_MEETINGS_PER_MONTH_KEY,
          parseLimitInput(maxMeetingsPerMonth),
          reason.trim()
        ),
        billingApi.setEntitlement(token, plan.id, TOOLS_KEY, Array.from(tools), reason.trim()),
      ]);
      setReason("");
      await load();
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save this plan's limits.");
    } finally {
      setSaving(false);
    }
  }

  const activePrice = prices?.find((p) => p.status === "active");

  return (
    <Card
      title={plan.name}
      action={
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs text-text-tertiary">{plan.code}</span>
          <Badge label={plan.status} tone={plan.status === "active" ? "success" : "neutral"} />
        </div>
      }
    >
      {error ? <p className="mb-3 text-xs text-danger">{error}</p> : null}

      <p className="mb-4 text-sm text-text-secondary">
        {activePrice
          ? `${(activePrice.amount_cents / 100).toFixed(2)} ${activePrice.currency} / ${activePrice.billing_interval}`
          : "No active price set — see the Pricing page."}
      </p>

      {entitlements === null ? (
        <p className="text-xs text-text-tertiary">Loading…</p>
      ) : (
        <>
          <div className="mb-4 grid grid-cols-3 gap-3">
            <label className="block">
              <span className="mb-1.5 block text-xs font-medium text-text-secondary">
                Max guests
              </span>
              <input
                disabled={!canAction}
                value={maxGuests}
                onChange={(e) => setMaxGuests(e.target.value)}
                placeholder="Unlimited"
                inputMode="numeric"
                className="w-full rounded border border-border bg-surface px-2 py-1.5 text-sm text-text-primary outline-none focus:border-accent disabled:opacity-50"
              />
            </label>
            <label className="block">
              <span className="mb-1.5 block text-xs font-medium text-text-secondary">
                Max minutes / meeting
              </span>
              <input
                disabled={!canAction}
                value={maxMinutes}
                onChange={(e) => setMaxMinutes(e.target.value)}
                placeholder="Unlimited"
                inputMode="numeric"
                className="w-full rounded border border-border bg-surface px-2 py-1.5 text-sm text-text-primary outline-none focus:border-accent disabled:opacity-50"
              />
            </label>
            <label className="block">
              <span className="mb-1.5 block text-xs font-medium text-text-secondary">
                Meetings / month
              </span>
              <input
                disabled={!canAction}
                value={maxMeetingsPerMonth}
                onChange={(e) => setMaxMeetingsPerMonth(e.target.value)}
                placeholder="Unlimited"
                inputMode="numeric"
                className="w-full rounded border border-border bg-surface px-2 py-1.5 text-sm text-text-primary outline-none focus:border-accent disabled:opacity-50"
              />
            </label>
          </div>
          <p className="mb-2 text-xs text-text-tertiary">
            Currently: {maxGuests || "unlimited"} guests ·{" "}
            {minutesToHoursLabel(maxMinutes === "" ? null : Number(maxMinutes))} per meeting ·{" "}
            {maxMeetingsPerMonth || "unlimited"} meetings/month. Leave a field blank for unlimited.
          </p>

          <p className="mb-2 mt-4 text-xs font-medium uppercase tracking-widest text-text-tertiary">
            Tools included
          </p>
          <div className="mb-4 grid grid-cols-2 gap-x-4 gap-y-1.5 sm:grid-cols-3">
            {CONFERENCE_TOOLS.map((tool) => (
              <label key={tool.id} className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  disabled={!canAction}
                  checked={tools.has(tool.id)}
                  onChange={() => toggleTool(tool.id)}
                  className="mt-0.5"
                />
                <span className="text-text-primary" title={tool.description}>
                  {tool.label}
                  {!tool.enforced ? (
                    <span className="ml-1 text-text-tertiary">(informational)</span>
                  ) : null}
                </span>
              </label>
            ))}
          </div>

          {canAction ? (
            <div className="flex items-end gap-2 border-t border-border pt-4">
              <label className="flex-1">
                <span className="mb-1.5 block text-xs font-medium text-text-secondary">
                  Reason (audit-logged)
                </span>
                <input
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="e.g. launch pricing pass"
                  className="w-full rounded border border-border bg-surface px-2 py-1.5 text-sm text-text-primary outline-none focus:border-accent"
                />
              </label>
              <Button loading={saving} disabled={!reason.trim()} onClick={handleSave}>
                Save limits &amp; tools
              </Button>
            </div>
          ) : null}
        </>
      )}
    </Card>
  );
}
