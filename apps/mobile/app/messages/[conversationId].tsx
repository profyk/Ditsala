import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  RefreshControl,
  Text,
  TextInput,
  View,
} from "react-native";

import { Avatar } from "../../components/Avatar";
import { Icon } from "../../components/Icon";
import { Screen } from "../../components/Screen";
import { authApi } from "../../lib/api";
import { decryptIncomingMessage, encryptOutgoingMessage } from "../../lib/crypto/chat-crypto";
import { randomId } from "../../lib/id";
import {
  type Conversation,
  type ConversationMember,
  type Message,
  messagingApi,
} from "../../lib/messaging-api";
import { messagingSocket } from "../../lib/messaging-ws";
import { getAccessToken } from "../../lib/session";
import { useTheme } from "../../lib/theme-context";

/**
 * The chat screen — a real-time view, not a load-once-and-forget one.
 * Every event the transport already carries (message.new/.edited/
 * .deleted/.delivered/.read, typing) is now actually consumed here;
 * previously only message.new was handled, and even that triggered a
 * full reload + re-decrypt of the *entire* history on every single
 * incoming message — a cost that only grew with the conversation.
 */

interface DecryptedMessage extends Message {
  plaintext: string | null;
  // Client-only, never persisted: an optimistically-inserted message
  // still in flight, or one whose send failed and can be retried.
  pending?: boolean;
  failed?: boolean;
}

type ReceiptStatus = "sent" | "delivered" | "read";

const TYPING_SEND_THROTTLE_MS = 3000;
const TYPING_EXPIRE_MS = 6000;
const RECENT_WINDOW = 30;

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

export default function ChatScreen() {
  const router = useRouter();
  const { colors } = useTheme();
  const { conversationId } = useLocalSearchParams<{ conversationId: string }>();

  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [members, setMembers] = useState<ConversationMember[]>([]);
  const [ownUserId, setOwnUserId] = useState<string | null>(null);
  const [ownDeviceId, setOwnDeviceId] = useState<string | null>(null);
  const [messages, setMessages] = useState<DecryptedMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [hasMoreOlder, setHasMoreOlder] = useState(true);
  const [replyingTo, setReplyingTo] = useState<DecryptedMessage | null>(null);
  const [openActionsFor, setOpenActionsFor] = useState<string | null>(null);
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState("");
  const [typingUserIds, setTypingUserIds] = useState<Set<string>>(new Set());
  const [receipts, setReceipts] = useState<Record<string, ReceiptStatus>>({});
  const [focused, setFocused] = useState(false);

  const tokenRef = useRef<string | null>(null);
  const conversationRef = useRef<Conversation | null>(null);
  const messagesRef = useRef<DecryptedMessage[]>([]);
  const readMarkedRef = useRef<Set<string>>(new Set());
  const lastTypingSentRef = useRef(0);
  const typingTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  useEffect(() => {
    conversationRef.current = conversation;
  }, [conversation]);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useFocusEffect(
    useCallback(() => {
      setFocused(true);
      return () => setFocused(false);
    }, [])
  );

  const decryptOne = useCallback(
    async (token: string, conv: Conversation, raw: Message): Promise<DecryptedMessage> => {
      if (raw.deleted_at) return { ...raw, plaintext: null };
      return {
        ...raw,
        plaintext: await decryptIncomingMessage(token, conv, raw.sender_device_id, raw.ciphertext),
      };
    },
    []
  );

  /** Marks every not-yet-marked incoming message in `list` as read —
   * fire-and-forget, best-effort (a receipt failing shouldn't block
   * reading the conversation). */
  const markIncomingAsRead = useCallback(
    (token: string, list: DecryptedMessage[]) => {
      const toMark = list.filter(
        (m) =>
          m.sender_device_id !== ownDeviceId &&
          !m.deleted_at &&
          !readMarkedRef.current.has(m.id)
      );
      if (toMark.length === 0) return;
      for (const m of toMark) readMarkedRef.current.add(m.id);
      Promise.all(toMark.map((m) => messagingApi.markReceipt(token, m.id, "read"))).catch(
        () => undefined
      );
    },
    [ownDeviceId]
  );

  const load = useCallback(async () => {
    const token = await getAccessToken();
    if (!token || !conversationId) {
      router.replace("/");
      return;
    }
    tokenRef.current = token;
    try {
      const [me, conversations, memberList] = await Promise.all([
        authApi.getMe(token),
        messagingApi.listConversations(token),
        messagingApi.listConversationMembers(token, conversationId),
      ]);
      const conv = conversations.find((c) => c.id === conversationId);
      if (!conv) {
        setError("This conversation is no longer available.");
        return;
      }
      setOwnUserId(me.id);
      setConversation(conv);
      setMembers(memberList);
      const primaryDevice = await messagingApi.getPrimaryDevice(token, me.id);
      setOwnDeviceId(primaryDevice);

      const raw = await messagingApi.listMessages(token, conversationId, {
        limit: RECENT_WINDOW,
      });
      const decrypted = await Promise.all(raw.map((m) => decryptOne(token, conv, m)));
      setMessages(decrypted);
      setHasMoreOlder(raw.length === RECENT_WINDOW);
      setError(null);
      markIncomingAsRead(token, decrypted);
    } catch {
      setError("Could not load this conversation.");
    }
  }, [conversationId, router, decryptOne, markIncomingAsRead]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleRefresh() {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }

  async function handleLoadOlder() {
    const token = tokenRef.current;
    const conv = conversationRef.current;
    const oldest = messagesRef.current[messagesRef.current.length - 1];
    if (!token || !conv || !oldest || loadingOlder || !hasMoreOlder) return;
    setLoadingOlder(true);
    try {
      const raw = await messagingApi.listMessages(token, conversationId, {
        before: oldest.created_at,
        limit: RECENT_WINDOW,
      });
      const decrypted = await Promise.all(raw.map((m) => decryptOne(token, conv, m)));
      setMessages((current) => [...current, ...decrypted]);
      setHasMoreOlder(raw.length === RECENT_WINDOW);
    } catch {
      // A failed "load more" shouldn't disturb what's already on screen.
    } finally {
      setLoadingOlder(false);
    }
  }

  /** Re-fetches just the recent window and merges it into local state —
   * reused messages are never re-decrypted; only ids not already held
   * locally (or explicitly `force`d, e.g. a known edit) pay that cost.
   * Replaces the old "reload + re-decrypt everything" behavior. */
  const mergeRecent = useCallback(
    async (forceId?: string) => {
      const token = tokenRef.current;
      const conv = conversationRef.current;
      if (!token || !conv) return;
      const raw = await messagingApi.listMessages(token, conversationId, {
        limit: RECENT_WINDOW,
      });
      const existingById = new Map(messagesRef.current.map((m) => [m.id, m]));
      const merged = await Promise.all(
        raw.map(async (m): Promise<DecryptedMessage> => {
          const existing = existingById.get(m.id);
          if (existing && !existing.pending && m.id !== forceId) return existing;
          return decryptOne(token, conv, m);
        })
      );
      const mergedIds = new Set(merged.map((m) => m.id));
      const olderKept = messagesRef.current.filter(
        (m) => !mergedIds.has(m.id) && !m.pending
      );
      const stillPending = messagesRef.current.filter((m) => m.pending);
      const next = [...stillPending, ...merged, ...olderKept];
      setMessages(next);
      if (focused) markIncomingAsRead(token, merged);
    },
    [conversationId, decryptOne, focused, markIncomingAsRead]
  );

  useEffect(() => {
    return messagingSocket.onEvent((event) => {
      if (!("conversation_id" in event) || event.conversation_id !== conversationId) return;
      switch (event.type) {
        case "message.new":
        case "message.edited":
          mergeRecent(event.type === "message.edited" ? event.message_id : undefined);
          break;
        case "message.deleted":
          setMessages((current) =>
            current.map((m) => (m.id === event.message_id ? { ...m, plaintext: null, deleted_at: new Date().toISOString() } : m))
          );
          break;
        case "message.delivered":
        case "message.read":
          if (event.user_id !== ownUserId) {
            setReceipts((current) => ({
              ...current,
              [event.message_id]: event.type === "message.read" ? "read" : "delivered",
            }));
          }
          break;
        case "typing": {
          if (event.user_id === ownUserId) break;
          setTypingUserIds((current) => new Set(current).add(event.user_id));
          const existingTimer = typingTimersRef.current.get(event.user_id);
          if (existingTimer) clearTimeout(existingTimer);
          typingTimersRef.current.set(
            event.user_id,
            setTimeout(() => {
              setTypingUserIds((current) => {
                const next = new Set(current);
                next.delete(event.user_id);
                return next;
              });
              typingTimersRef.current.delete(event.user_id);
            }, TYPING_EXPIRE_MS)
          );
          break;
        }
        default:
          break;
      }
    });
  }, [conversationId, mergeRecent, ownUserId]);

  useEffect(() => {
    const timers = typingTimersRef.current;
    return () => {
      for (const timer of timers.values()) clearTimeout(timer);
    };
  }, []);

  function handleDraftChange(text: string) {
    setDraft(text);
    const now = Date.now();
    if (now - lastTypingSentRef.current > TYPING_SEND_THROTTLE_MS) {
      lastTypingSentRef.current = now;
      messagingSocket.sendTyping(conversationId);
    }
  }

  async function handleSend() {
    const token = tokenRef.current;
    const conv = conversation;
    if (!token || !conv || !ownUserId || draft.trim().length === 0) return;
    const text = draft.trim();
    const replyToMessageId = replyingTo?.id;
    setDraft("");
    setReplyingTo(null);
    setSending(true);

    const tempId = `pending-${randomId()}`;
    const optimistic: DecryptedMessage = {
      id: tempId,
      conversation_id: conv.id,
      sender_device_id: ownDeviceId,
      ciphertext: new Uint8Array(),
      content_type: "text",
      client_message_id: tempId,
      reply_to_message_id: replyToMessageId ?? null,
      edited_at: null,
      deleted_at: null,
      expires_at: null,
      created_at: new Date().toISOString(),
      plaintext: text,
      pending: true,
    };
    setMessages((current) => [optimistic, ...current]);

    try {
      const ciphertext = await encryptOutgoingMessage(token, conv, members, ownUserId, text);
      const sent = await messagingApi.sendMessage(token, conv.id, {
        ciphertext,
        contentType: "text",
        clientMessageId: tempId,
        replyToMessageId,
      });
      setMessages((current) =>
        current.map((m) => (m.id === tempId ? { ...sent, plaintext: text } : m))
      );
      setReceipts((current) => ({ ...current, [sent.id]: "sent" }));
    } catch {
      setMessages((current) =>
        current.map((m) => (m.id === tempId ? { ...m, pending: false, failed: true } : m))
      );
      setError("Could not send that message.");
    } finally {
      setSending(false);
    }
  }

  async function handleRetry(message: DecryptedMessage) {
    const token = tokenRef.current;
    const conv = conversation;
    if (!token || !conv || !ownUserId || !message.plaintext) return;
    setMessages((current) =>
      current.map((m) => (m.id === message.id ? { ...m, pending: true, failed: false } : m))
    );
    try {
      const ciphertext = await encryptOutgoingMessage(
        token,
        conv,
        members,
        ownUserId,
        message.plaintext
      );
      const sent = await messagingApi.sendMessage(token, conv.id, {
        ciphertext,
        contentType: "text",
        clientMessageId: message.id,
        replyToMessageId: message.reply_to_message_id ?? undefined,
      });
      setMessages((current) =>
        current.map((m) => (m.id === message.id ? { ...sent, plaintext: message.plaintext } : m))
      );
    } catch {
      setMessages((current) =>
        current.map((m) => (m.id === message.id ? { ...m, pending: false, failed: true } : m))
      );
    }
  }

  async function handleSaveEdit(messageId: string) {
    const token = tokenRef.current;
    const conv = conversation;
    const text = editDraft.trim();
    if (!token || !conv || !ownUserId || text.length === 0) return;
    try {
      const ciphertext = await encryptOutgoingMessage(token, conv, members, ownUserId, text);
      const updated = await messagingApi.editMessage(token, messageId, ciphertext);
      setMessages((current) =>
        current.map((m) => (m.id === messageId ? { ...updated, plaintext: text } : m))
      );
      setEditingMessageId(null);
      setEditDraft("");
    } catch {
      setError("Could not save that edit.");
    }
  }

  async function handleDelete(messageId: string) {
    const token = tokenRef.current;
    if (!token) return;
    setOpenActionsFor(null);
    try {
      await messagingApi.deleteMessage(token, messageId);
      setMessages((current) =>
        current.map((m) =>
          m.id === messageId ? { ...m, plaintext: null, deleted_at: new Date().toISOString() } : m
        )
      );
    } catch {
      setError("Could not delete that message.");
    }
  }

  const otherMember = members.find((m) => m.user_id !== ownUserId);
  const title =
    conversation?.type === "group"
      ? (conversation.title ?? members.map((m) => m.display_name).join(", "))
      : (otherMember?.display_name ?? "Chat");

  function nameFor(userId: string): string {
    return members.find((m) => m.user_id === userId)?.display_name ?? "Someone";
  }

  const typingLabel =
    typingUserIds.size === 0
      ? null
      : typingUserIds.size === 1
        ? `${nameFor([...typingUserIds][0])} is typing…`
        : "Several people are typing…";

  function messageById(id: string | null): DecryptedMessage | undefined {
    if (!id) return undefined;
    return messages.find((m) => m.id === id);
  }

  return (
    <Screen scroll={false}>
      <View className="mb-3 mt-8 flex-row items-center gap-3">
        <Pressable
          testID="chat-back-button"
          onPress={() => router.back()}
          className="h-9 w-9 items-center justify-center rounded-full active:bg-surface-raised"
        >
          <Icon name="chevron-left" size={20} color={colors.textPrimary} />
        </Pressable>
        <Avatar
          id={conversation?.id ?? "chat"}
          name={title}
          imageUrl={conversation?.type === "direct" ? otherMember?.avatar_url : null}
          size={38}
        />
        <View className="flex-1">
          <Text className="text-lg font-bold text-text-primary" numberOfLines={1}>
            {title}
          </Text>
          {typingLabel ? (
            <Text className="text-xs text-accent" numberOfLines={1}>
              {typingLabel}
            </Text>
          ) : null}
        </View>
      </View>

      {error ? <Text className="mb-2 text-sm text-danger">{error}</Text> : null}

      <FlatList
        className="flex-1"
        // `messagingApi.listMessages` returns newest-first (matches the
        // backend's own `ORDER BY created_at DESC`) — exactly what an
        // `inverted` FlatList wants at index 0 (rendered at the bottom,
        // the initial scroll position), so this is used as-is.
        data={messages}
        inverted
        keyExtractor={(item) => item.id}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={handleRefresh} tintColor={colors.accent} />
        }
        onEndReached={handleLoadOlder}
        onEndReachedThreshold={0.4}
        renderItem={({ item }) => {
          const isOwn = item.sender_device_id !== null && item.sender_device_id === ownDeviceId;
          const isDeleted = item.deleted_at !== null;
          const repliedTo = messageById(item.reply_to_message_id);
          const isEditing = editingMessageId === item.id;
          const actionsOpen = openActionsFor === item.id;
          const receipt = receipts[item.id];

          return (
            <Pressable
              onPress={() =>
                !item.pending && !isDeleted
                  ? setOpenActionsFor(actionsOpen ? null : item.id)
                  : undefined
              }
              className={`mb-2 max-w-[80%] ${isOwn ? "self-end" : "self-start"}`}
            >
              {repliedTo ? (
                <View className="mb-1 rounded-lg border-l-2 border-accent bg-surface-raised px-2 py-1">
                  <Text className="text-xs text-text-tertiary" numberOfLines={1}>
                    {repliedTo.deleted_at
                      ? "Original message deleted"
                      : (repliedTo.plaintext ?? "…")}
                  </Text>
                </View>
              ) : null}

              {isEditing ? (
                <View className="gap-2 rounded-2xl border border-accent bg-surface px-3 py-2">
                  <TextInput
                    testID={`chat-edit-input-${item.id}`}
                    value={editDraft}
                    onChangeText={setEditDraft}
                    multiline
                    autoFocus
                    className="text-text-primary"
                  />
                  <View className="flex-row justify-end gap-3">
                    <Pressable onPress={() => setEditingMessageId(null)}>
                      <Text className="text-xs text-text-secondary">Cancel</Text>
                    </Pressable>
                    <Pressable onPress={() => handleSaveEdit(item.id)}>
                      <Text className="text-xs font-semibold text-accent">Save</Text>
                    </Pressable>
                  </View>
                </View>
              ) : (
                <View
                  className={`rounded-2xl px-4 py-2.5 ${
                    isDeleted
                      ? "border border-dashed border-border bg-transparent"
                      : isOwn
                        ? "bg-accent"
                        : "border border-border bg-surface"
                  } ${item.pending ? "opacity-60" : ""}`}
                >
                  <Text
                    className={
                      isDeleted
                        ? "italic text-text-tertiary"
                        : isOwn
                          ? "text-white"
                          : "text-text-primary"
                    }
                  >
                    {isDeleted
                      ? "This message was deleted"
                      : (item.plaintext ?? "Couldn't decrypt this message")}
                  </Text>
                </View>
              )}

              <View className={`mt-1 flex-row items-center gap-1 ${isOwn ? "self-end" : "self-start"}`}>
                {item.edited_at && !isDeleted ? (
                  <Text className="text-xs text-text-tertiary">edited ·</Text>
                ) : null}
                <Text className="text-xs text-text-tertiary">
                  {item.failed ? "Failed to send" : item.pending ? "Sending…" : formatTime(item.created_at)}
                </Text>
                {isOwn && !item.pending && !item.failed ? (
                  <Icon
                    name="check"
                    size={12}
                    color={receipt === "read" ? colors.accent : colors.textTertiary}
                  />
                ) : null}
              </View>

              {actionsOpen && !isDeleted && !item.pending ? (
                <View className="mt-1 flex-row gap-3 rounded-lg border border-border bg-surface px-3 py-2">
                  <Pressable
                    testID={`chat-reply-${item.id}`}
                    onPress={() => {
                      setReplyingTo(item);
                      setOpenActionsFor(null);
                    }}
                  >
                    <Text className="text-xs font-medium text-accent">Reply</Text>
                  </Pressable>
                  {isOwn ? (
                    <Pressable
                      testID={`chat-edit-${item.id}`}
                      onPress={() => {
                        setEditingMessageId(item.id);
                        setEditDraft(item.plaintext ?? "");
                        setOpenActionsFor(null);
                      }}
                    >
                      <Text className="text-xs font-medium text-text-secondary">Edit</Text>
                    </Pressable>
                  ) : null}
                  {isOwn ? (
                    <Pressable testID={`chat-delete-${item.id}`} onPress={() => handleDelete(item.id)}>
                      <Text className="text-xs font-medium text-danger">Delete</Text>
                    </Pressable>
                  ) : null}
                  {item.failed ? (
                    <Pressable onPress={() => handleRetry(item)}>
                      <Text className="text-xs font-medium text-accent">Retry</Text>
                    </Pressable>
                  ) : null}
                </View>
              ) : null}
            </Pressable>
          );
        }}
        ListEmptyComponent={
          <View className="flex-1 items-center justify-center py-16">
            <View
              className="mb-3 h-14 w-14 items-center justify-center rounded-full"
              style={{ backgroundColor: colors.accentMuted }}
            >
              <Icon name="messages" size={26} color={colors.accent} />
            </View>
            <Text className="text-base font-semibold text-text-primary">Say hello</Text>
            <Text className="mt-1 text-center text-sm text-text-tertiary">
              Every message here is end-to-end encrypted.
            </Text>
          </View>
        }
      />

      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined}>
        {replyingTo ? (
          <View className="flex-row items-center gap-2 border-t border-border bg-surface-raised px-3 py-2">
            <View className="flex-1">
              <Text className="text-xs font-medium text-accent">Replying</Text>
              <Text className="text-xs text-text-tertiary" numberOfLines={1}>
                {replyingTo.plaintext ?? "…"}
              </Text>
            </View>
            <Pressable onPress={() => setReplyingTo(null)}>
              <Icon name="close" size={16} color={colors.textTertiary} />
            </Pressable>
          </View>
        ) : null}
        <View className="flex-row items-center gap-2 border-t border-border pb-4 pt-3">
          <TextInput
            testID="chat-input"
            value={draft}
            onChangeText={handleDraftChange}
            placeholder="Message"
            placeholderTextColor={colors.textTertiary}
            multiline
            className="flex-1 rounded-2xl border border-border bg-surface px-4 py-2.5 text-text-primary"
          />
          <Pressable
            testID="chat-send-button"
            onPress={handleSend}
            disabled={sending || draft.trim().length === 0}
            className="h-11 w-11 items-center justify-center rounded-full bg-accent disabled:opacity-50"
          >
            <Icon name="send" size={18} color="#FFFFFF" />
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </Screen>
  );
}
