"use client";

import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { TextField } from "@/components/TextField";
import { adminApi, type SystemConfigEntry } from "@/lib/admin-api";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { roleHasPermission } from "@/lib/rbac";

export default function SystemConfigPage() {
  const { token, role } = useAuth();
  const [configs, setConfigs] = useState<SystemConfigEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [newKey, setNewKey] = useState("");
  const [newValue, setNewValue] = useState("{}");
  const [newReason, setNewReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [jsonError, setJsonError] = useState<string | null>(null);

  const canAction = role ? roleHasPermission(role, "system_config:action") : false;

  const load = useCallback(async () => {
    if (!token) return;
    try {
      setConfigs(await adminApi.listSystemConfig(token));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load system config.");
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleSet(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !newKey.trim() || !newReason.trim()) return;
    setJsonError(null);
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(newValue);
    } catch {
      setJsonError("Value must be valid JSON, e.g. {\"enabled\": true}");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await adminApi.setSystemConfig(token, newKey, parsed, newReason);
      setNewKey("");
      setNewValue("{}");
      setNewReason("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="max-w-2xl">
      <h1 className="mb-1 font-display text-2xl font-semibold text-text-primary">
        System Configuration
      </h1>
      <p className="mb-8 text-sm text-text-tertiary">
        Key/value editor over <code>system_config</code> — SOS cancel window, feature flags, etc.
        Every change is audit-logged with before/after value (§28.8).
      </p>

      {error ? <p className="mb-4 text-sm text-danger">{error}</p> : null}

      <div className="mb-6 space-y-3">
        {configs.map((config) => (
          <div key={config.key} className="rounded border border-border bg-surface p-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="font-mono text-sm text-text-primary">{config.key}</span>
              <span className="text-xs text-text-tertiary">
                {new Date(config.updated_at).toLocaleString()}
              </span>
            </div>
            <pre className="overflow-x-auto rounded bg-surface-raised p-2 text-xs text-text-secondary">
              {JSON.stringify(config.value, null, 2)}
            </pre>
          </div>
        ))}
        {configs.length === 0 ? (
          <p className="text-sm text-text-tertiary">No configuration keys set yet.</p>
        ) : null}
      </div>

      {canAction ? (
        <Card title="Set a key">
          <form onSubmit={handleSet}>
            <TextField
              label="Key"
              placeholder="e.g. sos_cancel_window_seconds"
              value={newKey}
              onChange={(e) => setNewKey(e.target.value)}
              required
            />
            <label className="mb-4 block">
              <span className="mb-1.5 block text-sm font-medium text-text-secondary">
                Value (JSON)
              </span>
              <textarea
                className="w-full rounded border border-border bg-surface px-3 py-2 font-mono text-sm text-text-primary outline-none focus:border-accent"
                rows={3}
                value={newValue}
                onChange={(e) => setNewValue(e.target.value)}
              />
              {jsonError ? <span className="mt-1 block text-xs text-danger">{jsonError}</span> : null}
            </label>
            <TextField
              label="Reason (audit-logged)"
              value={newReason}
              onChange={(e) => setNewReason(e.target.value)}
              required
            />
            <Button type="submit" loading={submitting} disabled={!newKey.trim() || !newReason.trim()}>
              Save
            </Button>
          </form>
        </Card>
      ) : null}
    </div>
  );
}
