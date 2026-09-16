"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { TextField } from "@/components/TextField";
import { kycApi, type KycDetail } from "@/lib/admin-api";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

type ActionKind = "approve" | "reject" | "request-recapture";

export default function KycDetailPage() {
  const { userId } = useParams<{ userId: string }>();
  const router = useRouter();
  const { token } = useAuth();

  const [accessReason, setAccessReason] = useState("");
  const [detail, setDetail] = useState<KycDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  const [actionKind, setActionKind] = useState<ActionKind | null>(null);
  const [actionReason, setActionReason] = useState("");
  const [submittingAction, setSubmittingAction] = useState(false);

  async function handleRequestAccess(e: React.FormEvent) {
    e.preventDefault();
    if (!token) return;
    setError(null);
    setLoadingDetail(true);
    try {
      setDetail(await kycApi.getDetail(token, userId, accessReason));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load KYC detail.");
    } finally {
      setLoadingDetail(false);
    }
  }

  async function handleAction(kind: ActionKind) {
    if (!token || !actionReason.trim()) return;
    setSubmittingAction(true);
    setError(null);
    try {
      const fn =
        kind === "approve"
          ? kycApi.approve
          : kind === "reject"
            ? kycApi.reject
            : kycApi.requestRecapture;
      await fn(token, userId, actionReason);
      router.push("/kyc");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not complete action.");
    } finally {
      setSubmittingAction(false);
    }
  }

  if (!detail) {
    return (
      <div className="max-w-md">
        <h1 className="mb-1 font-display text-2xl font-semibold text-text-primary">
          KYC Review
        </h1>
        <p className="mb-6 text-sm text-text-tertiary">
          §5/§28.2: a reason for access is required and logged before any P1 (biometric/KYC)
          detail is shown — not an afterthought.
        </p>
        {error ? <p className="mb-4 text-sm text-danger">{error}</p> : null}
        <form onSubmit={handleRequestAccess}>
          <TextField
            label="Reason for access"
            value={accessReason}
            onChange={(e) => setAccessReason(e.target.value)}
            placeholder="e.g. Flagged for manual review — document mismatch"
            required
          />
          <Button type="submit" loading={loadingDetail}>
            View KYC detail
          </Button>
        </form>
      </div>
    );
  }

  return (
    <div className="max-w-2xl">
      <h1 className="mb-1 font-display text-2xl font-semibold text-text-primary">
        {detail.user.display_name}
      </h1>
      <p className="mb-6 text-sm text-text-tertiary">
        {detail.user.email} · {detail.user.phone}
      </p>

      {error ? <p className="mb-4 text-sm text-danger">{error}</p> : null}

      <Card title="Document verification" >
        {detail.documents.length === 0 ? (
          <p className="text-sm text-text-tertiary">No documents on file.</p>
        ) : (
          <div className="space-y-3">
            {detail.documents.map((doc) => (
              <div key={doc.id} className="rounded border border-border p-3">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-sm text-text-primary">{doc.document_type}</span>
                  <Badge
                    label={doc.status}
                    tone={doc.status === "passed" ? "success" : doc.status === "failed" ? "danger" : "warning"}
                  />
                </div>
                {doc.result_summary ? (
                  <pre className="overflow-x-auto rounded bg-surface-raised p-2 text-xs text-text-tertiary">
                    {JSON.stringify(doc.result_summary, null, 2)}
                  </pre>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </Card>

      <div className="h-4" />

      <Card title="Liveness / face match">
        {detail.face_verifications.length === 0 ? (
          <p className="text-sm text-text-tertiary">No liveness checks on file.</p>
        ) : (
          <div className="space-y-3">
            {detail.face_verifications.map((face) => (
              <div key={face.id} className="rounded border border-border p-3">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-sm text-text-primary">Liveness check</span>
                  <Badge
                    label={face.status}
                    tone={face.status === "passed" ? "success" : face.status === "failed" ? "danger" : "warning"}
                  />
                </div>
                <p className="text-xs text-text-tertiary">
                  Liveness score: {face.selfie_liveness_score ?? "—"} · Face match:{" "}
                  {face.face_match_score ?? "—"}
                </p>
              </div>
            ))}
          </div>
        )}
      </Card>

      <div className="h-4" />

      <Card title="Decision">
        {actionKind ? (
          <div>
            <p className="mb-3 text-sm text-text-secondary">
              Confirm: <strong className="text-text-primary">{actionKind.replace("-", " ")}</strong>
            </p>
            <TextField
              label="Reason"
              value={actionReason}
              onChange={(e) => setActionReason(e.target.value)}
              required
            />
            <div className="flex gap-3">
              <Button
                variant={actionKind === "reject" ? "danger" : "primary"}
                loading={submittingAction}
                disabled={!actionReason.trim()}
                onClick={() => handleAction(actionKind)}
              >
                Confirm {actionKind.replace("-", " ")}
              </Button>
              <Button variant="secondary" onClick={() => setActionKind(null)}>
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex gap-3">
            <Button onClick={() => setActionKind("approve")}>Approve</Button>
            <Button variant="secondary" onClick={() => setActionKind("request-recapture")}>
              Request recapture
            </Button>
            <Button variant="danger" onClick={() => setActionKind("reject")}>
              Reject
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
}
