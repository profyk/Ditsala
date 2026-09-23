"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { adminApi, type DataSubjectRequest } from "@/lib/admin-api";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { roleHasPermission } from "@/lib/rbac";

const STATUSES = ["pending", "in_progress", "completed", "rejected"] as const;

const STATUS_TONE: Record<string, "neutral" | "warning" | "success" | "danger"> = {
  pending: "neutral",
  in_progress: "warning",
  completed: "success",
  rejected: "danger",
};

export default function DataSubjectRequestsPage() {
  const { token, role } = useAuth();
  const canAction = role ? roleHasPermission(role, "data_subject_requests:action") : false;

  const [status, setStatus] = useState<(typeof STATUSES)[number]>("pending");
  const [requests, setRequests] = useState<DataSubjectRequest[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    setRequests(null);
    try {
      setRequests(await adminApi.listDataSubjectRequests(token, status));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load requests.");
    }
  }, [token, status]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleMarkInProgress(id: string) {
    if (!token) return;
    setBusyId(id);
    setError(null);
    try {
      await adminApi.markDataSubjectRequestInProgress(token, id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update this request.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleComplete(id: string) {
    if (!token) return;
    const notes = window.prompt("Resolution notes (required)?");
    if (!notes) return;
    setBusyId(id);
    setError(null);
    try {
      await adminApi.completeDataSubjectRequest(token, id, notes);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not complete this request.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleReject(id: string) {
    if (!token) return;
    const notes = window.prompt("Reason for rejecting (required)?");
    if (!notes) return;
    setBusyId(id);
    setError(null);
    try {
      await adminApi.rejectDataSubjectRequest(token, id, notes);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reject this request.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="max-w-3xl">
      <h1 className="mb-1 font-display text-2xl font-semibold text-text-primary">
        Data Subject Requests
      </h1>
      <p className="mb-8 text-sm text-text-tertiary">
        Access, correction, and deletion requests (§34.4) — tracked against a 30-day SLA computed
        at filing time. Completing a deletion request genuinely deactivates the account; it isn&apos;t
        a separate code path.
      </p>

      <div className="mb-6 flex gap-2">
        {STATUSES.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setStatus(s)}
            className={`rounded-full border px-3 py-1 text-xs font-medium capitalize transition-colors ${
              status === s
                ? "border-accent bg-accent-muted text-accent"
                : "border-border text-text-secondary hover:text-text-primary"
            }`}
          >
            {s.replace(/_/g, " ")}
          </button>
        ))}
      </div>

      {error ? <p className="mb-4 text-sm text-danger">{error}</p> : null}

      <div className="space-y-3">
        {requests === null ? (
          <p className="text-sm text-text-tertiary">Loading…</p>
        ) : requests.length === 0 ? (
          <p className="text-sm text-text-tertiary">No {status.replace(/_/g, " ")} requests.</p>
        ) : (
          requests.map((r) => (
            <Card
              key={r.id}
              title={`${r.request_type} — user ${r.user_id.slice(0, 8)}…`}
              action={<Badge label={r.status} tone={STATUS_TONE[r.status] ?? "neutral"} />}
            >
              <p className="mb-1 text-xs text-text-tertiary">
                Filed {new Date(r.created_at).toLocaleString()} · Due{" "}
                {new Date(r.due_at).toLocaleDateString()}
              </p>
              {r.details ? (
                <p className="mb-3 text-sm text-text-secondary">{r.details}</p>
              ) : null}
              {r.resolution_notes ? (
                <p className="mb-3 rounded bg-surface-raised p-2 text-xs text-text-secondary">
                  {r.resolution_notes}
                </p>
              ) : null}
              {canAction && (r.status === "pending" || r.status === "in_progress") ? (
                <div className="flex gap-2">
                  {r.status === "pending" ? (
                    <Button
                      variant="secondary"
                      onClick={() => handleMarkInProgress(r.id)}
                      loading={busyId === r.id}
                    >
                      Mark in progress
                    </Button>
                  ) : null}
                  <Button
                    variant="primary"
                    onClick={() => handleComplete(r.id)}
                    loading={busyId === r.id}
                  >
                    Complete
                  </Button>
                  <Button
                    variant="danger"
                    onClick={() => handleReject(r.id)}
                    loading={busyId === r.id}
                  >
                    Reject
                  </Button>
                </div>
              ) : null}
            </Card>
          ))
        )}
      </div>
    </div>
  );
}
