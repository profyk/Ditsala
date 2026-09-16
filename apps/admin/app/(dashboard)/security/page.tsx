"use client";

import { useEffect, useState } from "react";

import { StatCard } from "@/components/Card";
import { adminApi, type SecuritySummary } from "@/lib/admin-api";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

export default function SecurityPage() {
  const { token } = useAuth();
  const [summary, setSummary] = useState<SecuritySummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    adminApi
      .getSecuritySummary(token)
      .then(setSummary)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load."));
  }, [token]);

  return (
    <div>
      <h1 className="mb-1 font-display text-2xl font-semibold text-text-primary">
        Security Dashboard
      </h1>
      <p className="mb-8 text-sm text-text-tertiary">
        Login-attempt anomalies, lockouts, device churn, and active sessions (§28.5).
      </p>

      {error ? <p className="text-sm text-danger">{error}</p> : null}

      {summary ? (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatCard label="Locked accounts" value={summary.locked_accounts} />
          <StatCard label="Failed logins (24h)" value={summary.failed_logins_last_24h} />
          <StatCard label="Active sessions" value={summary.active_sessions} />
          <StatCard label="New devices (24h)" value={summary.new_devices_last_24h} />
        </div>
      ) : (
        <p className="text-sm text-text-tertiary">Loading…</p>
      )}
    </div>
  );
}
