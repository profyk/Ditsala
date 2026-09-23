"use client";

import { useState } from "react";

import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { TextField } from "@/components/TextField";
import { billingApi, type Plan } from "@/lib/admin-api";
import { ApiError } from "@/lib/api";

/**
 * There's no self-serve payment flow for the four Conference Room tiers
 * yet (see backend `PlanService.set_user_conference_plan`'s docstring —
 * same "admin sets it, no default by design" precedent VIP pricing
 * already established) — this is how an admin actually grants one.
 */
export function AssignUserPlanForm({
  token,
  conferencePlans,
}: {
  token: string | null;
  conferencePlans: Plan[];
}) {
  const [userId, setUserId] = useState("");
  const [planCode, setPlanCode] = useState(conferencePlans[0]?.code ?? "");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !userId.trim() || !planCode || !reason.trim()) return;
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await billingApi.setUserConferencePlan(
        token,
        userId.trim(),
        planCode,
        reason.trim()
      );
      setSuccess(`User ${result.user_id} is now on ${result.conference_plan_code}.`);
      setReason("");
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not assign this Conference plan."
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card title="Assign a user's Conference plan">
      <p className="mb-4 text-sm text-text-tertiary">
        Grants one user a Conference Room tier directly — there's no self-serve checkout for
        these four plans yet. Every change is audit-logged with before/after.
      </p>
      {error ? <p className="mb-3 text-xs text-danger">{error}</p> : null}
      {success ? <p className="mb-3 text-xs text-success">{success}</p> : null}
      <form onSubmit={handleSubmit}>
        <TextField
          label="User ID"
          placeholder="UUID"
          value={userId}
          onChange={(e) => setUserId(e.target.value)}
          required
        />
        <label className="mb-4 block">
          <span className="mb-1.5 block text-sm font-medium text-text-secondary">Plan</span>
          <select
            className="w-full rounded border border-border bg-surface px-3 py-2 text-sm text-text-primary outline-none focus:border-accent"
            value={planCode}
            onChange={(e) => setPlanCode(e.target.value)}
          >
            {conferencePlans.map((p) => (
              <option key={p.code} value={p.code}>
                {p.name} ({p.code})
              </option>
            ))}
          </select>
        </label>
        <TextField
          label="Reason"
          placeholder="e.g. upgraded via support ticket #123"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          required
        />
        <Button
          type="submit"
          loading={saving}
          disabled={!userId.trim() || !planCode || !reason.trim()}
        >
          Assign plan
        </Button>
      </form>
    </Card>
  );
}
