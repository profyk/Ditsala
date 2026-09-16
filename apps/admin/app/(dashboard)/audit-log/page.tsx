"use client";

import { useCallback, useEffect, useState } from "react";

import { TextField } from "@/components/TextField";
import { adminApi, type AuditLogEntry } from "@/lib/admin-api";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

export default function AuditLogPage() {
  const { token } = useAuth();
  const [action, setAction] = useState("");
  const [targetType, setTargetType] = useState("");
  const [entries, setEntries] = useState<AuditLogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      setEntries(
        await adminApi.listAuditLog(token, {
          action: action || undefined,
          target_type: targetType || undefined,
          limit: 100,
        })
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load audit log.");
    }
  }, [token, action, targetType]);

  useEffect(() => {
    const handle = setTimeout(load, 300);
    return () => clearTimeout(handle);
  }, [load]);

  return (
    <div>
      <h1 className="mb-1 font-display text-2xl font-semibold text-text-primary">Audit Log</h1>
      <p className="mb-6 text-sm text-text-tertiary">
        Immutable, filterable (§28.7) — insert-only at the DB grant level, no admin path can
        edit or delete an entry.
      </p>

      <div className="mb-6 flex gap-4">
        <div className="w-64">
          <TextField
            label="Action"
            placeholder="e.g. admin.kyc.approved"
            value={action}
            onChange={(e) => setAction(e.target.value)}
          />
        </div>
        <div className="w-48">
          <TextField
            label="Target type"
            placeholder="e.g. user"
            value={targetType}
            onChange={(e) => setTargetType(e.target.value)}
          />
        </div>
      </div>

      {error ? <p className="mb-4 text-sm text-danger">{error}</p> : null}

      <div className="overflow-hidden rounded border border-border">
        <table className="w-full text-sm">
          <thead className="bg-surface-raised text-left text-xs uppercase tracking-wide text-text-tertiary">
            <tr>
              <th className="px-4 py-3">When</th>
              <th className="px-4 py-3">Actor</th>
              <th className="px-4 py-3">Action</th>
              <th className="px-4 py-3">Target</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {entries.map((entry) => (
              <tr key={entry.id} className="align-top bg-surface">
                <td className="px-4 py-3 whitespace-nowrap text-text-tertiary">
                  {new Date(entry.created_at).toLocaleString()}
                </td>
                <td className="px-4 py-3 text-text-secondary">
                  {entry.actor_type}
                  {entry.actor_id ? ` · ${entry.actor_id.slice(0, 8)}` : ""}
                </td>
                <td className="px-4 py-3 font-medium text-text-primary">{entry.action}</td>
                <td className="px-4 py-3 text-text-tertiary">
                  {entry.target_type ? (
                    <span>
                      {entry.target_type}
                      {entry.target_id ? ` · ${entry.target_id.slice(0, 8)}` : ""}
                    </span>
                  ) : (
                    "—"
                  )}
                  {entry.metadata_json ? (
                    <pre className="mt-1 max-w-md overflow-x-auto rounded bg-surface-raised p-2 text-xs">
                      {JSON.stringify(entry.metadata_json)}
                    </pre>
                  ) : null}
                </td>
              </tr>
            ))}
            {entries.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-text-tertiary">
                  No matching entries.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}
