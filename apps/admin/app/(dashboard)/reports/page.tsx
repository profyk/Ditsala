"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { TextField } from "@/components/TextField";
import { adminApi, type Report } from "@/lib/admin-api";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { roleHasPermission } from "@/lib/rbac";

type ActionKind = "warn" | "suspend" | "ban";

export default function ReportsPage() {
  const { token, role } = useAuth();
  const [status, setStatus] = useState("open");
  const [reports, setReports] = useState<Report[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [activeReport, setActiveReport] = useState<string | null>(null);
  const [actionKind, setActionKind] = useState<ActionKind>("warn");
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const canAction = role ? roleHasPermission(role, "reports:action") : false;

  const load = useCallback(async () => {
    if (!token) return;
    try {
      setReports(await adminApi.listReports(token, status));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load reports.");
    }
  }, [token, status]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleAction(reportId: string) {
    if (!token || !reason.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await adminApi.actionReport(token, reportId, actionKind, reason);
      setActiveReport(null);
      setReason("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not action report.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div>
      <h1 className="mb-1 font-display text-2xl font-semibold text-text-primary">
        Reports & Moderation
      </h1>
      <p className="mb-6 text-sm text-text-tertiary">
        Metadata only — never message plaintext, which the app can't decrypt server-side anyway
        (§24).
      </p>

      <div className="mb-6 flex gap-2">
        {["open", "reviewed", "actioned"].map((s) => (
          <button
            key={s}
            onClick={() => setStatus(s)}
            className={`rounded px-3 py-1.5 text-sm capitalize ${
              status === s
                ? "bg-accent-muted text-accent"
                : "text-text-secondary hover:bg-surface-raised"
            }`}
          >
            {s}
          </button>
        ))}
      </div>

      {error ? <p className="mb-4 text-sm text-danger">{error}</p> : null}

      <div className="space-y-3">
        {reports.map((report) => (
          <div key={report.id} className="rounded border border-border bg-surface p-4">
            <div className="mb-2 flex items-center justify-between">
              <Badge label={report.status} tone={report.status === "open" ? "warning" : "neutral"} />
              <span className="text-xs text-text-tertiary">
                {new Date(report.created_at).toLocaleString()}
              </span>
            </div>
            <p className="mb-1 text-sm text-text-primary">{report.reason}</p>
            <p className="mb-3 text-xs text-text-tertiary">
              Reported user: {report.reported_user_id}
            </p>

            {canAction && report.status === "open" ? (
              activeReport === report.id ? (
                <div>
                  <div className="mb-3 flex gap-2">
                    {(["warn", "suspend", "ban"] as ActionKind[]).map((kind) => (
                      <button
                        key={kind}
                        onClick={() => setActionKind(kind)}
                        className={`rounded px-3 py-1 text-xs capitalize ${
                          actionKind === kind
                            ? "bg-accent text-background"
                            : "bg-surface-raised text-text-secondary"
                        }`}
                      >
                        {kind}
                      </button>
                    ))}
                  </div>
                  <TextField
                    label="Reason"
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    required
                  />
                  <div className="flex gap-3">
                    <Button
                      variant={actionKind === "ban" ? "danger" : "primary"}
                      loading={submitting}
                      disabled={!reason.trim()}
                      onClick={() => handleAction(report.id)}
                    >
                      Confirm {actionKind}
                    </Button>
                    <Button variant="secondary" onClick={() => setActiveReport(null)}>
                      Cancel
                    </Button>
                  </div>
                </div>
              ) : (
                <Button variant="secondary" onClick={() => setActiveReport(report.id)}>
                  Action this report
                </Button>
              )
            ) : null}
          </div>
        ))}
        {reports.length === 0 ? (
          <p className="py-8 text-center text-sm text-text-tertiary">No {status} reports.</p>
        ) : null}
      </div>
    </div>
  );
}
