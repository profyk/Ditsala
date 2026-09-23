"use client";

import { useCallback, useEffect, useState } from "react";

import { Card, StatCard } from "@/components/Card";
import { type PlanRevenueLine, type RevenueOverview, revenueApi } from "@/lib/admin-api";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

function formatCents(cents: number, currency: string | null): string {
  if (!currency) return "—";
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(cents / 100);
  } catch {
    return `${currency} ${(cents / 100).toFixed(2)}`;
  }
}

const PRODUCT_LABEL: Record<string, string> = {
  free: "Free tier",
  vip: "VIP",
  business: "Business",
  conference: "Conference Room",
};

/**
 * A read-only aggregate over Plans/Entitlements + current account-tier
 * headcounts — see backend `app/domain/admin/revenue.py`'s docstring for
 * exactly what "estimated" means (a current-state snapshot, not a
 * reconciled ledger — `estimated_monthly_cents` = active monthly price ×
 * current subscriber count).
 */
export default function RevenuePage() {
  const { token } = useAuth();
  const [overview, setOverview] = useState<RevenueOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      setOverview(await revenueApi.getOverview(token));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load revenue overview.");
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  const currency = overview?.lines.find((l) => l.price_currency)?.price_currency ?? null;

  return (
    <div className="max-w-4xl">
      <h1 className="mb-1 font-display text-2xl font-semibold text-text-primary">
        Revenue &amp; Subscriptions
      </h1>
      <p className="mb-8 text-sm text-text-tertiary">
        An estimated snapshot — active monthly price × current subscribers per plan, not a
        reconciled ledger. Real charge history lives with Stitch/VIP subscriptions.
      </p>

      {error ? <p className="mb-4 text-sm text-danger">{error}</p> : null}

      {overview === null ? (
        <p className="text-sm text-text-tertiary">Loading…</p>
      ) : (
        <>
          <div className="mb-8 grid grid-cols-2 gap-4 sm:grid-cols-3">
            <StatCard
              label="Estimated MRR"
              value={formatCents(overview.total_estimated_monthly_cents, currency ?? "ZAR")}
            />
            <StatCard label="Total subscribers" value={overview.total_subscribers} />
            <StatCard label="Active plans" value={overview.lines.length} />
          </div>

          <div className="space-y-3">
            {overview.lines
              .slice()
              .sort((a, b) => b.estimated_monthly_cents - a.estimated_monthly_cents)
              .map((line) => (
                <PlanLineCard key={line.plan_id} line={line} />
              ))}
          </div>
        </>
      )}
    </div>
  );
}

function PlanLineCard({ line }: { line: PlanRevenueLine }) {
  return (
    <Card
      title={line.plan_name}
      action={
        <span className="text-xs text-text-tertiary">{PRODUCT_LABEL[line.product] ?? line.product}</span>
      }
    >
      <div className="grid grid-cols-3 gap-4 text-sm">
        <div>
          <p className="text-xs text-text-tertiary">Subscribers</p>
          <p className="font-medium text-text-primary">{line.subscriber_count}</p>
        </div>
        <div>
          <p className="text-xs text-text-tertiary">Price / month</p>
          <p className="font-medium text-text-primary">
            {line.price_amount_cents !== null
              ? formatCents(line.price_amount_cents, line.price_currency)
              : "No price set"}
          </p>
        </div>
        <div>
          <p className="text-xs text-text-tertiary">Est. monthly</p>
          <p className="font-medium text-text-primary">
            {formatCents(line.estimated_monthly_cents, line.price_currency ?? "ZAR")}
          </p>
        </div>
      </div>
    </Card>
  );
}
