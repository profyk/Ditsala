"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AccountStateBadge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { TextField } from "@/components/TextField";
import { adminApi, type AuditLogEntry, type UserSummary } from "@/lib/admin-api";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { roleHasPermission } from "@/lib/rbac";

const FORCEABLE_STATES = ["active", "manual_review", "suspended", "deactivated", "banned"];

export default function UserDetailPage() {
  const { userId } = useParams<{ userId: string }>();
  const { token, role } = useAuth();
  const [user, setUser] = useState<UserSummary | null>(null);
  const [history, setHistory] = useState<AuditLogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [newState, setNewState] = useState("");
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const canAction = role ? roleHasPermission(role, "users:action") : false;

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const [u, h] = await Promise.all([
        adminApi.getUser(token, userId),
        adminApi.getUserHistory(token, userId),
      ]);
      setUser(u);
      setHistory(h);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load user.");
    }
  }, [token, userId]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleForceState(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !newState || !reason.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await adminApi.forceAccountState(token, userId, newState, reason);
      setReason("");
      setNewState("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update account state.");
    } finally {
      setSubmitting(false);
    }
  }

  if (!user) {
    return <p className="text-sm text-text-tertiary">{error ?? "Loading…"}</p>;
  }

  return (
    <div className="max-w-2xl">
      <div className="mb-1 flex items-center gap-3">
        <h1 className="font-display text-2xl font-semibold text-text-primary">
          {user.display_name}
        </h1>
        <AccountStateBadge state={user.account_state} />
      </div>
      <p className="mb-8 text-sm text-text-tertiary">
        {user.email} · {user.phone} · joined {new Date(user.created_at).toLocaleDateString()}
      </p>

      {error ? <p className="mb-4 text-sm text-danger">{error}</p> : null}

      {canAction ? (
        <Card title="Force account state">
          <form onSubmit={handleForceState}>
            <label className="mb-4 block">
              <span className="mb-1.5 block text-sm font-medium text-text-secondary">
                New state
              </span>
              <select
                className="w-full rounded border border-border bg-surface px-3 py-2 text-sm text-text-primary outline-none focus:border-accent"
                value={newState}
                onChange={(e) => setNewState(e.target.value)}
                required
              >
                <option value="">Select a state…</option>
                {FORCEABLE_STATES.map((s) => (
                  <option key={s} value={s}>
                    {s.replace(/_/g, " ")}
                  </option>
                ))}
              </select>
            </label>
            <TextField
              label="Reason (required, audit-logged)"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              required
            />
            <Button type="submit" loading={submitting} disabled={!newState || !reason.trim()}>
              Apply
            </Button>
          </form>
        </Card>
      ) : null}

      <div className="h-4" />

      <Card title="History">
        {history.length === 0 ? (
          <p className="text-sm text-text-tertiary">No recorded actions yet.</p>
        ) : (
          <ul className="space-y-3">
            {history.map((entry) => (
              <li key={entry.id} className="border-b border-border pb-3 last:border-0 last:pb-0">
                <p className="text-sm text-text-primary">{entry.action}</p>
                <p className="text-xs text-text-tertiary">
                  {new Date(entry.created_at).toLocaleString()}
                </p>
                {entry.metadata_json ? (
                  <pre className="mt-1 overflow-x-auto rounded bg-surface-raised p-2 text-xs text-text-tertiary">
                    {JSON.stringify(entry.metadata_json, null, 2)}
                  </pre>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
