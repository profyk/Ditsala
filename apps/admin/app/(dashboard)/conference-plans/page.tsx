"use client";

import { useCallback, useEffect, useState } from "react";

import { AssignUserPlanForm } from "@/components/conference-plans/AssignUserPlanForm";
import { ConferencePlanCard } from "@/components/conference-plans/ConferencePlanCard";
import { billingApi, type Plan } from "@/lib/admin-api";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { CONFERENCE_PRODUCT } from "@/lib/conference-plans";
import { roleHasPermission } from "@/lib/rbac";

/**
 * A structured, Conference-Room-specific view over the same
 * plans/prices/entitlements backend the generic `/pricing` page already
 * covers — that page stays the raw JSON editor for every product;  this
 * one renders the four conference_* plans with labeled guest/duration/
 * tool fields instead, and adds assigning a plan to one user (no
 * self-serve checkout exists for these tiers yet).
 */
export default function ConferencePlansPage() {
  const { token, role } = useAuth();
  const canAction = role ? roleHasPermission(role, "billing_plans:action") : false;

  const [plans, setPlans] = useState<Plan[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const all = await billingApi.listPlans(token);
      setPlans(all.filter((p) => p.product === CONFERENCE_PRODUCT));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load Conference plans.");
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  const activePlans = (plans ?? []).filter((p) => p.status === "active");

  return (
    <div className="max-w-4xl">
      <h1 className="mb-1 font-display text-2xl font-semibold text-text-primary">
        Conference Plans
      </h1>
      <p className="mb-8 text-sm text-text-tertiary">
        Free / Pro / Premium / Enterprise — guest limits, meeting-length caps, and which tools
        each tier includes. Seeded by migration <code>b4f7c1a9e6d2</code>; everything below is
        the same admin-editable data the generic{" "}
        <a href="/pricing" className="text-accent hover:underline">
          Pricing
        </a>{" "}
        page exposes as raw entitlement JSON, just with real fields.
      </p>

      {error ? <p className="mb-4 text-sm text-danger">{error}</p> : null}

      {plans === null ? (
        <p className="text-sm text-text-tertiary">Loading…</p>
      ) : plans.length === 0 ? (
        <p className="text-sm text-text-tertiary">
          No Conference plans found — run migrations, or create one from the Pricing page with
          product <code>conference</code>.
        </p>
      ) : (
        <div className="mb-8 space-y-4">
          {plans.map((plan) => (
            <ConferencePlanCard
              key={plan.id}
              plan={plan}
              token={token}
              canAction={canAction}
              onChanged={load}
            />
          ))}
        </div>
      )}

      {canAction && activePlans.length > 0 ? (
        <AssignUserPlanForm token={token} conferencePlans={activePlans} />
      ) : null}
    </div>
  );
}
