"use client";

import { LiveKitRoom, VideoConference } from "@livekit/components-react";
import { useParams } from "next/navigation";
import { useState } from "react";

import { type JoinMeetingResponse, ApiError, meetingsApi } from "@/lib/api";

/**
 * Phase 1 join flow (docs/DITSALA_MEET_SPEC.md §9) — guest join only for
 * now. A DITSALA-account host flow (reusing the same login this app's
 * sibling apps already have) is the next real increment, not built here
 * yet — see that section's own scope note.
 */
export default function MeetingRoom() {
  const params = useParams<{ meetingId: string }>();
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [join, setJoin] = useState<JoinMeetingResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleJoin(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const result = await meetingsApi.guestJoin(
        params.meetingId,
        displayName.trim(),
        password || undefined
      );
      setJoin(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not join this meeting.");
    } finally {
      setSubmitting(false);
    }
  }

  if (join) {
    return (
      <LiveKitRoom
        serverUrl={join.access.livekit_url}
        token={join.access.token}
        connect
        data-lk-theme="default"
        style={{ height: "100vh" }}
        onDisconnected={() => setJoin(null)}
      >
        <VideoConference />
      </LiveKitRoom>
    );
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 px-4">
      <h1 className="font-display text-3xl text-text-primary">Join meeting</h1>
      <form className="flex w-full max-w-sm flex-col gap-3" onSubmit={handleJoin}>
        <input
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          placeholder="Your name"
          required
          className="rounded border border-border bg-surface px-4 py-2 text-text-primary outline-none focus:border-accent"
        />
        <input
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Meeting password (if required)"
          type="password"
          className="rounded border border-border bg-surface px-4 py-2 text-text-primary outline-none focus:border-accent"
        />
        {error ? <p className="text-sm text-danger">{error}</p> : null}
        <button
          type="submit"
          disabled={submitting || displayName.trim().length === 0}
          className="rounded bg-accent px-4 py-2 font-medium text-background hover:bg-accent-pressed disabled:opacity-50"
        >
          {submitting ? "Joining…" : "Join now"}
        </button>
      </form>
    </main>
  );
}
