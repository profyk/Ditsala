"use client";

import { useEffect, useState } from "react";

import { ApiError, type QuestionResponse, meetingsApi } from "@/lib/api";

const POLL_MS = 5000;

/**
 * Q&A — every participant, guests included, asks and upvotes (public
 * given a valid participant_id); host answers/dismisses via `hostToken`.
 */
export function QuestionsPanel({
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
  const [questions, setQuestions] = useState<QuestionResponse[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);

  async function refresh() {
    try {
      const list = await meetingsApi.listQuestions(meetingId, participantId);
      list.sort((a, b) => b.upvote_count - a.upvote_count);
      setQuestions(list);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load questions.");
    }
  }

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [meetingId, participantId]);

  async function handleAsk(e: React.FormEvent) {
    e.preventDefault();
    if (!draft.trim()) return;
    setSending(true);
    setError(null);
    try {
      await meetingsApi.askQuestion(meetingId, participantId, draft.trim());
      setDraft("");
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not send your question.");
    } finally {
      setSending(false);
    }
  }

  async function upvote(questionId: string) {
    try {
      await meetingsApi.upvoteQuestion(meetingId, questionId, participantId);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not upvote.");
    }
  }

  async function answer(questionId: string) {
    if (!hostToken) return;
    try {
      await meetingsApi.answerQuestion(meetingId, questionId, hostToken);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not mark this answered.");
    }
  }

  async function dismiss(questionId: string) {
    if (!hostToken) return;
    try {
      await meetingsApi.dismissQuestion(meetingId, questionId, hostToken);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not dismiss this question.");
    }
  }

  return (
    <div className="w-80 rounded border border-border bg-surface p-3 text-sm">
      <p className="mb-2 text-xs font-medium uppercase tracking-widest text-text-tertiary">
        Q&amp;A
      </p>
      {questions.length === 0 ? (
        <p className="text-text-tertiary">No questions yet.</p>
      ) : (
        <ul className="mb-3 flex flex-col gap-2">
          {questions.map((q) => (
            <li
              key={q.id}
              className={`rounded border p-2 ${
                q.status === "dismissed"
                  ? "border-border opacity-50"
                  : q.status === "answered"
                    ? "border-success/40"
                    : "border-border"
              }`}
            >
              <p className="text-text-primary">{q.body}</p>
              <div className="mt-1 flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => upvote(q.id)}
                  disabled={q.status !== "open"}
                  className="text-xs text-accent hover:underline disabled:opacity-50"
                >
                  ▲ {q.upvote_count}
                </button>
                {q.status === "answered" ? (
                  <span className="text-xs text-success">Answered</span>
                ) : q.status === "dismissed" ? (
                  <span className="text-xs text-text-tertiary">Dismissed</span>
                ) : isHost ? (
                  <>
                    <button
                      type="button"
                      onClick={() => answer(q.id)}
                      className="text-xs text-success hover:underline"
                    >
                      Mark answered
                    </button>
                    <button
                      type="button"
                      onClick={() => dismiss(q.id)}
                      className="text-xs text-text-tertiary hover:underline"
                    >
                      Dismiss
                    </button>
                  </>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={handleAsk} className="flex gap-1.5 border-t border-border pt-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask a question…"
          className="flex-1 rounded border border-border bg-background px-2 py-1 text-text-primary outline-none focus:border-accent"
        />
        <button
          type="submit"
          disabled={sending || !draft.trim()}
          className="rounded bg-accent px-3 py-1.5 text-xs font-medium text-background hover:bg-accent-pressed disabled:opacity-50"
        >
          Ask
        </button>
      </form>
      {error ? <p className="mt-2 text-xs text-danger">{error}</p> : null}
    </div>
  );
}
