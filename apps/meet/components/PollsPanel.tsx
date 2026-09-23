"use client";

import { useEffect, useState } from "react";

import { ApiError, type PollResponse, type PollResultsResponse, meetingsApi } from "@/lib/api";

const POLL_MS = 5000;

/**
 * Polls — host (via `hostToken`) creates and closes; every participant,
 * guests included, votes and sees results (public given a valid
 * participant_id — see backend's create_poll/vote_poll/get_poll_results).
 */
export function PollsPanel({
  meetingId,
  participantId,
  isHost,
  hostToken,
}: {
  meetingId: string;
  participantId: string;
  isHost: boolean;
  hostToken: string | null;
}) {
  const [polls, setPolls] = useState<PollResponse[]>([]);
  const [results, setResults] = useState<Record<string, PollResultsResponse>>({});
  const [error, setError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [options, setOptions] = useState(["", ""]);
  const [creating, setCreating] = useState(false);

  async function refresh() {
    try {
      const list = await meetingsApi.listPolls(meetingId, participantId);
      setPolls(list);
      const entries = await Promise.all(
        list.map(async (p) => [p.id, await meetingsApi.getPollResults(meetingId, p.id, participantId)] as const)
      );
      setResults(Object.fromEntries(entries));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load polls.");
    }
  }

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [meetingId, participantId]);

  async function vote(pollId: string, optionIndex: number) {
    try {
      await meetingsApi.votePoll(meetingId, pollId, participantId, optionIndex);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not record your vote.");
    }
  }

  async function close(pollId: string) {
    if (!hostToken) return;
    try {
      await meetingsApi.closePoll(meetingId, pollId, hostToken);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not close this poll.");
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    const cleanOptions = options.map((o) => o.trim()).filter(Boolean);
    if (!hostToken || !question.trim() || cleanOptions.length < 2) return;
    setCreating(true);
    setError(null);
    try {
      await meetingsApi.createPoll(meetingId, question.trim(), cleanOptions, hostToken);
      setQuestion("");
      setOptions(["", ""]);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create this poll.");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="w-80 rounded border border-border bg-surface p-3 text-sm">
      <p className="mb-2 text-xs font-medium uppercase tracking-widest text-text-tertiary">
        Polls
      </p>
      {polls.length === 0 ? (
        <p className="text-text-tertiary">No polls yet.</p>
      ) : (
        <ul className="mb-3 flex flex-col gap-3">
          {polls.map((poll) => {
            const counts = results[poll.id]?.counts ?? {};
            const total = Object.values(counts).reduce((a, b) => a + b, 0);
            return (
              <li key={poll.id} className="rounded border border-border p-2">
                <p className="mb-1.5 font-medium text-text-primary">{poll.question}</p>
                <div className="flex flex-col gap-1">
                  {poll.options.map((option, i) => {
                    const count = counts[String(i)] ?? 0;
                    const pct = total > 0 ? Math.round((count / total) * 100) : 0;
                    return (
                      <button
                        key={i}
                        type="button"
                        disabled={poll.closed_at !== null}
                        onClick={() => vote(poll.id, i)}
                        className="relative overflow-hidden rounded border border-border px-2 py-1 text-left text-text-primary disabled:opacity-70"
                      >
                        <div
                          className="absolute inset-y-0 left-0 bg-accent/15"
                          style={{ width: `${pct}%` }}
                        />
                        <span className="relative">
                          {option} — {count} ({pct}%)
                        </span>
                      </button>
                    );
                  })}
                </div>
                {isHost && poll.closed_at === null ? (
                  <button
                    type="button"
                    onClick={() => close(poll.id)}
                    className="mt-1.5 text-xs text-danger hover:underline"
                  >
                    Close poll
                  </button>
                ) : poll.closed_at !== null ? (
                  <p className="mt-1.5 text-xs text-text-tertiary">Closed</p>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
      {isHost ? (
        <form onSubmit={handleCreate} className="flex flex-col gap-1.5 border-t border-border pt-2">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask a question…"
            className="rounded border border-border bg-background px-2 py-1 text-text-primary outline-none focus:border-accent"
          />
          {options.map((opt, i) => (
            <input
              key={i}
              value={opt}
              onChange={(e) =>
                setOptions((prev) => prev.map((o, idx) => (idx === i ? e.target.value : o)))
              }
              placeholder={`Option ${i + 1}`}
              className="rounded border border-border bg-background px-2 py-1 text-text-primary outline-none focus:border-accent"
            />
          ))}
          <div className="flex items-center gap-2">
            {options.length < 6 ? (
              <button
                type="button"
                onClick={() => setOptions((prev) => [...prev, ""])}
                className="text-xs text-accent hover:underline"
              >
                + Add option
              </button>
            ) : null}
            <button
              type="submit"
              disabled={creating}
              className="ml-auto rounded bg-accent px-3 py-1.5 text-xs font-medium text-background hover:bg-accent-pressed disabled:opacity-50"
            >
              {creating ? "Creating…" : "Create poll"}
            </button>
          </div>
        </form>
      ) : null}
      {error ? <p className="mt-2 text-xs text-danger">{error}</p> : null}
    </div>
  );
}
