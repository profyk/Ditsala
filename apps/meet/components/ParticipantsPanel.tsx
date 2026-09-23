"use client";

import { useEffect, useState } from "react";

import { ApiError, type ParticipantResponse, meetingsApi } from "@/lib/api";

const HOST_ROLES = new Set(["host", "co_host"]);
const POLL_MS = 8000;

/**
 * Host/co-host moderation — who's actually in the meeting (not just the
 * waiting room), with mute/remove/promote. Separate from LiveKit's own
 * `<VideoConference />` participant tiles because those only know
 * LiveKit identities, not this backend's `MeetingParticipant.id` — the
 * id mute/remove/promote are keyed on. See
 * `MeetingService.list_participants`'s docstring.
 */
export function ParticipantsPanel({
  meetingId,
  hostToken,
  selfParticipantId,
}: {
  meetingId: string;
  hostToken: string;
  selfParticipantId: string;
}) {
  const [participants, setParticipants] = useState<ParticipantResponse[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  async function refresh() {
    try {
      setParticipants(await meetingsApi.listParticipants(meetingId, hostToken));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load participants.");
    }
  }

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [meetingId, hostToken]);

  async function withBusy(participantId: string, action: () => Promise<void>) {
    setBusyId(participantId);
    setError(null);
    try {
      await action();
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That action didn't go through.");
    } finally {
      setBusyId(null);
    }
  }

  const present = participants.filter((p) => p.admission_status === "admitted");

  return (
    <div className="w-80 rounded border border-border bg-surface p-3 text-sm">
      <p className="mb-2 text-xs font-medium uppercase tracking-widest text-text-tertiary">
        Participants ({present.length})
      </p>
      {present.length === 0 ? (
        <p className="text-text-tertiary">Nobody's here yet.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {present.map((p) => {
            const isSelf = p.id === selfParticipantId;
            const isHost = HOST_ROLES.has(p.role);
            return (
              <li key={p.id} className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-text-primary">
                    {p.guest_display_name || (isSelf ? "You" : "Participant")}
                    {isHost ? (
                      <span className="ml-1.5 text-xs text-accent">
                        {p.role === "host" ? "Host" : "Co-host"}
                      </span>
                    ) : null}
                  </p>
                </div>
                {!isSelf ? (
                  <div className="flex shrink-0 gap-1">
                    {!isHost ? (
                      <button
                        type="button"
                        disabled={busyId === p.id}
                        onClick={() =>
                          withBusy(p.id, () =>
                            meetingsApi.promoteCoHost(meetingId, p.id, hostToken).then(() => {})
                          )
                        }
                        className="rounded bg-surface-raised px-2 py-1 text-xs text-text-primary border border-border hover:bg-border disabled:opacity-50"
                      >
                        Make co-host
                      </button>
                    ) : null}
                    <button
                      type="button"
                      disabled={busyId === p.id}
                      onClick={() =>
                        withBusy(p.id, () =>
                          meetingsApi.muteParticipant(meetingId, p.id, true, hostToken)
                        )
                      }
                      className="rounded bg-surface-raised px-2 py-1 text-xs text-text-primary border border-border hover:bg-border disabled:opacity-50"
                    >
                      Mute
                    </button>
                    <button
                      type="button"
                      disabled={busyId === p.id}
                      onClick={() =>
                        withBusy(p.id, () => meetingsApi.removeParticipant(meetingId, p.id, hostToken))
                      }
                      className="rounded bg-danger/10 px-2 py-1 text-xs text-danger border border-danger/30 hover:bg-danger/20 disabled:opacity-50"
                    >
                      Remove
                    </button>
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
      {error ? <p className="mt-2 text-xs text-danger">{error}</p> : null}
    </div>
  );
}
