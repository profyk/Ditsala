"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Card, StatCard } from "@/components/Card";
import {
  type AdminConversationDetail,
  type AdminConversationSummary,
  type AdminMessageContext,
  messagingGovernanceApi,
} from "@/lib/admin-api";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { roleHasPermission } from "@/lib/rbac";

const PAGE_SIZE = 50;

const TYPE_TONE: Record<string, "accent" | "neutral" | "info"> = {
  direct: "neutral",
  group: "accent",
  vip_multilingual: "info",
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/**
 * Every conversation platform-wide, metadata only — the admin governance
 * equivalent of `GET /messaging/conversations`, which is scoped to "my
 * own conversations." Every field this page renders (member/message
 * counts, roles, timestamps) is metadata a conversation's own members
 * can already see; ciphertext is never fetched or displayed anywhere
 * here, by construction — see AdminMessagingGovernanceService's own
 * docstring for why this doesn't weaken §7.3's E2EE guarantee.
 */
export default function MessagingGovernancePage() {
  return (
    <Suspense fallback={<p className="text-sm text-text-tertiary">Loading…</p>}>
      <MessagingGovernancePageInner />
    </Suspense>
  );
}

/** Split out from the default export because `useSearchParams` (reading
 * a `?message=` deep link from the Reports page) requires a Suspense
 * boundary above it in the Next.js App Router — without one, static
 * generation for this route fails at build time. */
function MessagingGovernancePageInner() {
  const { token, role } = useAuth();
  const searchParams = useSearchParams();
  const deepLinkedMessageId = searchParams.get("message");
  const canAction = role ? roleHasPermission(role, "messaging_governance:action") : false;

  const [conversations, setConversations] = useState<AdminConversationSummary[] | null>(null);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const result = await messagingGovernanceApi.listConversations(token, {
        limit: PAGE_SIZE,
        offset,
      });
      setConversations(result.conversations);
      setTotal(result.total);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load conversations.");
    }
  }, [token, offset]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="max-w-4xl">
      <h1 className="mb-1 font-display text-2xl font-semibold text-text-primary">Messaging</h1>
      <p className="mb-6 text-sm text-text-tertiary">
        Every conversation platform-wide — metadata only (who&apos;s in it, how many messages,
        when). Message content is end-to-end encrypted and never available here, to any admin,
        by design.
      </p>

      <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-3">
        <StatCard label="Conversations" value={total} />
      </div>

      <MessageLookup token={token} canAction={canAction} initialMessageId={deepLinkedMessageId} />

      {error ? <p className="mb-4 text-sm text-danger">{error}</p> : null}

      {conversations === null ? (
        <p className="text-sm text-text-tertiary">Loading…</p>
      ) : conversations.length === 0 ? (
        <p className="text-sm text-text-tertiary">No conversations yet.</p>
      ) : (
        <div className="space-y-3">
          {conversations.map((conversation) => (
            <Card
              key={conversation.id}
              title={conversation.title ?? (conversation.type === "direct" ? "Direct message" : "Untitled group")}
              action={
                <div className="flex items-center gap-2">
                  <span className="text-xs text-text-tertiary">
                    {conversation.member_count} members · {conversation.message_count} messages
                  </span>
                  <Badge label={conversation.type} tone={TYPE_TONE[conversation.type] ?? "neutral"} />
                </div>
              }
            >
              <p className="mb-2 text-xs text-text-tertiary">
                Created {formatDate(conversation.created_at)}
              </p>
              <button
                type="button"
                onClick={() => setExpandedId(expandedId === conversation.id ? null : conversation.id)}
                className="text-xs text-accent hover:underline"
              >
                {expandedId === conversation.id ? "Hide members" : "View members"}
              </button>
              {expandedId === conversation.id ? (
                <ConversationDetail
                  token={token}
                  conversationId={conversation.id}
                  canAction={canAction}
                  onChanged={load}
                />
              ) : null}
            </Card>
          ))}
        </div>
      )}

      <div className="mt-4 flex items-center justify-between text-xs text-text-tertiary">
        <button
          type="button"
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          className="disabled:opacity-40"
        >
          ← Previous
        </button>
        <span>
          {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
        </span>
        <button
          type="button"
          disabled={offset + PAGE_SIZE >= total}
          onClick={() => setOffset(offset + PAGE_SIZE)}
          className="disabled:opacity-40"
        >
          Next →
        </button>
      </div>
    </div>
  );
}

function ConversationDetail({
  token,
  conversationId,
  canAction,
  onChanged,
}: {
  token: string | null;
  conversationId: string;
  canAction: boolean;
  onChanged: () => void;
}) {
  const [detail, setDetail] = useState<AdminConversationDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyUserId, setBusyUserId] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      setDetail(await messagingGovernanceApi.getConversation(token, conversationId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load this conversation.");
    }
  }, [token, conversationId]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleRemove(userId: string) {
    const reason = window.prompt("Reason for removing this member (audit-logged)?");
    if (!token || !reason?.trim()) return;
    setBusyUserId(userId);
    setError(null);
    try {
      await messagingGovernanceApi.removeMember(token, conversationId, userId, reason.trim());
      await load();
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not remove that member.");
    } finally {
      setBusyUserId(null);
    }
  }

  if (!detail) {
    return <p className="mt-2 text-xs text-text-tertiary">Loading…</p>;
  }

  return (
    <div className="mt-3 border-t border-border pt-3">
      {error ? <p className="mb-2 text-xs text-danger">{error}</p> : null}
      <ul className="space-y-1">
        {detail.members.map((member) => (
          <li key={member.user_id} className="flex items-center justify-between text-xs">
            <span className="text-text-primary">
              {member.display_name}
              {member.role === "admin" ? <span className="ml-1.5 text-accent">Admin</span> : null}
            </span>
            {canAction && detail.type === "group" ? (
              <button
                type="button"
                disabled={busyUserId === member.user_id}
                onClick={() => handleRemove(member.user_id)}
                className="text-danger hover:underline disabled:opacity-40"
              >
                Remove
              </button>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Resolves a message-level report's `context_ref` (a message id) to
 * enough metadata to act on it — the Reports & Moderation page links
 * here rather than duplicating this lookup+delete flow inline.
 */
function MessageLookup({
  token,
  canAction,
  initialMessageId,
}: {
  token: string | null;
  canAction: boolean;
  initialMessageId?: string | null;
}) {
  const [messageId, setMessageId] = useState(initialMessageId ?? "");
  const [context, setContext] = useState<AdminMessageContext | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const runLookup = useCallback(
    async (id: string) => {
      if (!token || !id.trim()) return;
      setLoading(true);
      setError(null);
      setContext(null);
      try {
        setContext(await messagingGovernanceApi.getMessageContext(token, id.trim()));
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Could not find that message.");
      } finally {
        setLoading(false);
      }
    },
    [token]
  );

  // Auto-run once a token is available, for a `?message=` deep link from
  // the Reports page — a reviewer clicking "view context" shouldn't have
  // to re-paste the id they just clicked through.
  useEffect(() => {
    if (initialMessageId && token) runLookup(initialMessageId);
  }, [initialMessageId, token, runLookup]);

  async function handleLookup(e: React.FormEvent) {
    e.preventDefault();
    await runLookup(messageId);
  }

  async function handleDelete() {
    const reason = window.prompt("Reason for deleting this message (audit-logged)?");
    if (!token || !context || !reason?.trim()) return;
    setDeleting(true);
    setError(null);
    try {
      await messagingGovernanceApi.deleteMessage(token, context.message_id, reason.trim());
      setContext({ ...context, deleted_at: new Date().toISOString() });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not delete that message.");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <Card title="Look up a reported message">
      <p className="mb-3 text-xs text-text-tertiary">
        Paste a message id from a report&apos;s context reference (Reports &amp; Moderation) to
        see who sent it, when, and whether it&apos;s already been removed. Content is never
        shown — it&apos;s end-to-end encrypted and this admin panel never has the key.
      </p>
      <form onSubmit={handleLookup} className="mb-3 flex items-end gap-2">
        <label className="flex-1">
          <span className="mb-1 block text-xs text-text-secondary">Message id</span>
          <input
            value={messageId}
            onChange={(e) => setMessageId(e.target.value)}
            placeholder="00000000-0000-0000-0000-000000000000"
            className="w-full rounded border border-border bg-surface px-2 py-1.5 text-sm text-text-primary outline-none focus:border-accent"
          />
        </label>
        <Button type="submit" variant="secondary" loading={loading} disabled={!messageId.trim()}>
          Look up
        </Button>
      </form>

      {error ? <p className="mb-2 text-xs text-danger">{error}</p> : null}

      {context ? (
        <div className="rounded border border-border bg-background p-3 text-xs">
          <p className="mb-1 text-text-primary">
            Conversation: <span className="text-text-secondary">{context.conversation_id}</span>
          </p>
          <p className="mb-1 text-text-primary">
            Sent by:{" "}
            <span className="text-text-secondary">{context.sender_user_id ?? "unknown"}</span>
          </p>
          <p className="mb-1 text-text-primary">
            Type: <span className="text-text-secondary">{context.content_type}</span> · Sent{" "}
            {formatDate(context.created_at)}
          </p>
          <p className="mb-3 text-text-primary">
            Status:{" "}
            {context.deleted_at ? (
              <Badge label="Deleted" tone="neutral" />
            ) : (
              <Badge label="Active" tone="success" />
            )}
          </p>
          {canAction && !context.deleted_at ? (
            <Button variant="danger" loading={deleting} onClick={handleDelete}>
              Delete this message
            </Button>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}
