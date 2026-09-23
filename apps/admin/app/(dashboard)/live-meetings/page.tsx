"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import {
  type AdminMeeting,
  type AdminMeetingAnalytics,
  type AdminMeetingParticipant,
  meetingsGovernanceApi,
} from "@/lib/admin-api";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { roleHasPermission } from "@/lib/rbac";

const POLL_MS = 15000;

function formatScheduled(iso: string | null): string {
  if (!iso) return "No scheduled time";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatDuration(seconds: number): string {
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

const STATUS_TONE: Record<string, "success" | "neutral" | "warning"> = {
  live: "success",
  scheduled: "neutral",
};

/**
 * Live/scheduled Conference Room meetings, platform-wide — governs what
 * `GET /meetings` (mobile app, scoped to "meetings I host") never could:
 * an admin seeing and acting on a meeting that isn't their own.
 */
export default function LiveMeetingsPage() {
  const { token, role } = useAuth();
  const canAction = role ? roleHasPermission(role, "meetings_governance:action") : false;

  const [meetings, setMeetings] = useState<AdminMeeting[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      setMeetings(await meetingsGovernanceApi.list(token));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load meetings.");
    }
  }, [token]);

  useEffect(() => {
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  return (
    <div className="max-w-4xl">
      <h1 className="mb-1 font-display text-2xl font-semibold text-text-primary">
        Live Meetings
      </h1>
      <p className="mb-8 text-sm text-text-tertiary">
        Every live or scheduled Conference Room meeting, across every host. Extend a live
        meeting's time, or end one — both audit-logged with a required reason.
      </p>

      {error ? <p className="mb-4 text-sm text-danger">{error}</p> : null}

      {meetings === null ? (
        <p className="text-sm text-text-tertiary">Loading…</p>
      ) : meetings.length === 0 ? (
        <p className="text-sm text-text-tertiary">No live or scheduled meetings right now.</p>
      ) : (
        <div className="space-y-3">
          {meetings.map((meeting) => (
            <Card
              key={meeting.id}
              title={meeting.title}
              action={
                <div className="flex items-center gap-2">
                  <span className="text-xs text-text-tertiary">
                    {meeting.active_participant_count} in room
                  </span>
                  <Badge
                    label={meeting.status}
                    tone={STATUS_TONE[meeting.status] ?? "neutral"}
                  />
                </div>
              }
            >
              <p className="mb-2 text-xs text-text-tertiary">
                {formatScheduled(meeting.scheduled_start_at)}
                {meeting.scheduled_duration_minutes
                  ? ` · ${meeting.scheduled_duration_minutes}min scheduled`
                  : ""}
                {meeting.duration_extended_minutes > 0
                  ? ` (+${meeting.duration_extended_minutes}min extended)`
                  : ""}
                {meeting.max_participants ? ` · cap ${meeting.max_participants}` : ""}
                {meeting.locked_at ? " · 🔒 locked" : ""}
              </p>
              <button
                type="button"
                onClick={() => setExpandedId(expandedId === meeting.id ? null : meeting.id)}
                className="text-xs text-accent hover:underline"
              >
                {expandedId === meeting.id ? "Hide details" : "View attendees & controls"}
              </button>
              {expandedId === meeting.id ? (
                <MeetingDetail
                  token={token}
                  meeting={meeting}
                  canAction={canAction}
                  onChanged={load}
                />
              ) : null}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function MeetingDetail({
  token,
  meeting,
  canAction,
  onChanged,
}: {
  token: string | null;
  meeting: AdminMeeting;
  canAction: boolean;
  onChanged: () => void;
}) {
  const [participants, setParticipants] = useState<AdminMeetingParticipant[] | null>(null);
  const [analytics, setAnalytics] = useState<AdminMeetingAnalytics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [extendMinutes, setExtendMinutes] = useState("15");
  const [extendReason, setExtendReason] = useState("");
  const [ending, setEnding] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token) return;
    Promise.all([
      meetingsGovernanceApi.listParticipants(token, meeting.id),
      meetingsGovernanceApi.getAnalytics(token, meeting.id),
    ])
      .then(([p, a]) => {
        setParticipants(p);
        setAnalytics(a);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load detail."));
  }, [token, meeting.id]);

  async function handleExtend(e: React.FormEvent) {
    e.preventDefault();
    const minutes = parseInt(extendMinutes, 10);
    if (!token || !extendReason.trim() || !Number.isFinite(minutes) || minutes <= 0) return;
    setBusy(true);
    setError(null);
    try {
      await meetingsGovernanceApi.extend(token, meeting.id, minutes, extendReason.trim());
      setExtendReason("");
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not extend this meeting.");
    } finally {
      setBusy(false);
    }
  }

  async function handleEnd() {
    const reason = window.prompt("Reason for ending this meeting (audit-logged)?");
    if (!token || !reason?.trim()) return;
    setBusy(true);
    setEnding(true);
    setError(null);
    try {
      await meetingsGovernanceApi.end(token, meeting.id, reason.trim());
      setEnding(false);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not end this meeting.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-3 border-t border-border pt-3">
      {error ? <p className="mb-2 text-xs text-danger">{error}</p> : null}

      {analytics ? (
        <p className="mb-3 text-xs text-text-secondary">
          {analytics.unique_attendees} unique attendees ({analytics.guest_attendees} guests) ·
          peak {analytics.peak_concurrent_attendees} at once · avg{" "}
          {formatDuration(analytics.average_attendance_seconds)} each
        </p>
      ) : null}

      <p className="mb-1 text-xs font-medium uppercase tracking-widest text-text-tertiary">
        Who attended
      </p>
      {participants === null ? (
        <p className="text-xs text-text-tertiary">Loading…</p>
      ) : participants.length === 0 ? (
        <p className="text-xs text-text-tertiary">No one has joined yet.</p>
      ) : (
        <ul className="mb-3 space-y-1">
          {participants.map((p) => (
            <li key={p.id} className="flex items-center justify-between text-xs">
              <span className="text-text-primary">
                {p.guest_display_name || (p.user_id ? "DITSALA user" : "Guest")}
                {p.role !== "participant" ? (
                  <span className="ml-1.5 text-accent">
                    {p.role === "host" ? "Host" : "Co-host"}
                  </span>
                ) : null}
              </span>
              <span className="text-text-tertiary">
                {p.joined_at
                  ? p.left_at
                    ? "left"
                    : "in room"
                  : p.admission_status === "waiting"
                    ? "waiting"
                    : "not joined"}
              </span>
            </li>
          ))}
        </ul>
      )}

      {canAction ? (
        <div className="flex flex-wrap items-end gap-3 border-t border-border pt-3">
          {meeting.status === "live" ? (
            <form onSubmit={handleExtend} className="flex items-end gap-2">
              <label>
                <span className="mb-1 block text-xs text-text-secondary">Extend by (min)</span>
                <input
                  value={extendMinutes}
                  onChange={(e) => setExtendMinutes(e.target.value)}
                  inputMode="numeric"
                  className="w-20 rounded border border-border bg-surface px-2 py-1.5 text-sm text-text-primary outline-none focus:border-accent"
                />
              </label>
              <label>
                <span className="mb-1 block text-xs text-text-secondary">Reason</span>
                <input
                  value={extendReason}
                  onChange={(e) => setExtendReason(e.target.value)}
                  placeholder="e.g. host requested more time"
                  className="w-56 rounded border border-border bg-surface px-2 py-1.5 text-sm text-text-primary outline-none focus:border-accent"
                />
              </label>
              <Button type="submit" variant="secondary" loading={busy} disabled={!extendReason.trim()}>
                Extend
              </Button>
            </form>
          ) : null}
          <Button variant="danger" loading={busy && ending} onClick={handleEnd}>
            End meeting
          </Button>
        </div>
      ) : null}
    </div>
  );
}
