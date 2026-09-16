"use client";

import { useEffect, useState } from "react";

import { StatCard } from "@/components/Card";
import { adminApi, type DashboardSummary } from "@/lib/admin-api";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

export default function DashboardPage() {
  const { token } = useAuth();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    adminApi
      .getDashboard(token)
      .then(setSummary)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load."));
  }, [token]);

  return (
    <div>
      <h1 className="mb-1 font-display text-2xl font-semibold text-text-primary">Dashboard</h1>
      <p className="mb-8 text-sm text-text-tertiary">
        Signups, KYC funnel, active accounts, and open reports at a glance.
      </p>

      {error ? <p className="text-sm text-danger">{error}</p> : null}

      {summary ? (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
          <StatCard label="Signups today" value={summary.signups_today} />
          <StatCard label="Signups this week" value={summary.signups_this_week} />
          <StatCard label="Active accounts" value={summary.active_accounts} />
          <StatCard label="In manual KYC review" value={summary.manual_review_count} />
          <StatCard label="Open reports" value={summary.open_reports_count} />
          <StatCard label="Pending invitations" value={summary.pending_invitations} />
        </div>
      ) : (
        <p className="text-sm text-text-tertiary">Loading…</p>
      )}
    </div>
  );
}
