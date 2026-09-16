"use client";

import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/Button";
import { Card, StatCard } from "@/components/Card";
import { TextField } from "@/components/TextField";
import { adminApi, type InvitationStats } from "@/lib/admin-api";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { roleHasPermission } from "@/lib/rbac";

export default function InvitationsPage() {
  const { token, role } = useAuth();
  const [enabled, setEnabled] = useState(false);
  const [stats, setStats] = useState<InvitationStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const canAction = role ? roleHasPermission(role, "invitations:action") : false;

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const [mode, s] = await Promise.all([
        adminApi.getInviteOnlyMode(token),
        adminApi.getInvitationStats(token),
      ]);
      setEnabled(mode.enabled);
      setStats(s);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load.");
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleToggle() {
    if (!token || !reason.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await adminApi.setInviteOnlyMode(token, !enabled, reason);
      setReason("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update setting.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="max-w-2xl">
      <h1 className="mb-1 font-display text-2xl font-semibold text-text-primary">Invitations</h1>
      <p className="mb-8 text-sm text-text-tertiary">
        Invite-only mode gates who can start onboarding — KYC is always required regardless
        (§22, §28.6).
      </p>

      {error ? <p className="mb-4 text-sm text-danger">{error}</p> : null}

      <Card title="Invite-only mode">
        <div className="mb-4 flex items-center gap-3">
          <span className="text-sm text-text-secondary">Currently</span>
          <span className={`text-sm font-semibold ${enabled ? "text-accent" : "text-text-tertiary"}`}>
            {enabled ? "ON" : "OFF"}
          </span>
        </div>
        {canAction ? (
          <div>
            <TextField
              label="Reason (audit-logged)"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
            <Button loading={submitting} disabled={!reason.trim()} onClick={handleToggle}>
              Turn {enabled ? "off" : "on"}
            </Button>
          </div>
        ) : null}
      </Card>

      <div className="h-4" />

      {stats ? (
        <>
          <div className="mb-4 grid grid-cols-3 gap-4">
            <StatCard label="Sent" value={stats.sent} />
            <StatCard label="Redeemed" value={stats.redeemed} />
            <StatCard label="Expired" value={stats.expired} />
          </div>
          <Card title="Top inviters">
            {stats.top_inviters.length === 0 ? (
              <p className="text-sm text-text-tertiary">No invitations sent yet.</p>
            ) : (
              <ul className="space-y-2">
                {stats.top_inviters.map((row) => (
                  <li
                    key={row.inviter_user_id}
                    className="flex justify-between border-b border-border pb-2 text-sm last:border-0"
                  >
                    <span className="text-text-secondary">{row.inviter_user_id}</span>
                    <span className="text-text-primary">{row.sent_count}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      ) : null}
    </div>
  );
}
