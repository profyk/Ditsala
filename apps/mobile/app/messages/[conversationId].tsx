import { RecordingPresets, requestRecordingPermissionsAsync, useAudioRecorder } from "expo-audio";
import { File } from "expo-file-system";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { VoiceNoteBubble } from "../../components/VoiceNoteBubble";
import { authApi } from "../../lib/api";
import {
  decryptIncomingMessage,
  decryptIncomingVoiceNoteKey,
  encryptOutgoingMessage,
  encryptOutgoingVoiceNote,
} from "../../lib/crypto/chat-crypto";
import { hashBytesHex } from "../../lib/crypto/e2ee";
import type { MediaKeyPayload } from "../../lib/crypto/wire";
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
  // Only set for content_type "voice_note" — undefined until decrypted,
  // null if decryption failed or this isn't a voice note.
  voiceNote?: MediaKeyPayload | null;
}

type ReceiptStatus = "sent" | "delivered" | "read";

const TYPING_SEND_THROTTLE_MS = 3000;
const TYPING_EXPIRE_MS = 6000;
const RECENT_WINDOW = 30;
const REACTION_EMOJI = ["❤️", "😂", "👍", "😮", "😢", "🙏"];

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
  const [isRecording, setIsRecording] = useState(false);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [sendingVoiceNote, setSendingVoiceNote] = useState(false);
  const [pinnedMessage, setPinnedMessage] = useState<DecryptedMessage | null>(null);
  const [reactionPickerFor, setReactionPickerFor] = useState<string | null>(null);

  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const recordingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

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
      if (raw.content_type === "voice_note") {
        const voiceNote = await decryptIncomingVoiceNoteKey(
          token,
          conv,
          raw.sender_device_id,
          raw.ciphertext
        );
        return { ...raw, plaintext: null, voiceNote };
      }
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

      const pinned = await messagingApi.getPinnedMessage(token, conversationId);
      setPinnedMessage(pinned ? await decryptOne(token, conv, pinned) : null);
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

  const refreshPinnedMessage = useCallback(async () => {
    const token = tokenRef.current;
    const conv = conversationRef.current;
    if (!token || !conv) return;
    const pinned = await messagingApi.getPinnedMessage(token, conversationId);
    setPinnedMessage(pinned ? await decryptOne(token, conv, pinned) : null);
  }, [conversationId, decryptOne]);

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
        case "message.pinned":
          refreshPinnedMessage();
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
  }, [conversationId, mergeRecent, ownUserId, refreshPinnedMessage]);

  useEffect(() => {
    const timers = typingTimersRef.current;
    return () => {
      for (const timer of timers.values()) clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    return () => {
      if (recordingTimerRef.current) clearInterval(recordingTimerRef.current);
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
      media_object_id: null,
      pinned_at: null,
      is_forwarded: false,
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

  async function handleStartRecording() {
    const permission = await requestRecordingPermissionsAsync();
    if (!permission.granted) {
      setError("Microphone access is needed to record a voice note.");
      return;
    }
    await recorder.prepareToRecordAsync();
    recorder.record();
    setIsRecording(true);
    setRecordingSeconds(0);
    recordingTimerRef.current = setInterval(() => {
      setRecordingSeconds(Math.round(recorder.currentTime));
    }, 250);
  }

  function stopRecordingTimer() {
    if (recordingTimerRef.current) {
      clearInterval(recordingTimerRef.current);
      recordingTimerRef.current = null;
    }
  }

  async function handleCancelRecording() {
    stopRecordingTimer();
    setIsRecording(false);
    try {
      await recorder.stop();
    } catch {
      // Nothing to send either way — a failed stop shouldn't block
      // getting back to the ordinary composer.
    }
  }

  async function handleSendVoiceNote() {
    const token = tokenRef.current;
    const conv = conversation;
    stopRecordingTimer();
    setIsRecording(false);
    if (!token || !conv || !ownUserId) return;
    setSendingVoiceNote(true);
    try {
      await recorder.stop();
      const uri = recorder.uri;
      if (!uri) throw new Error("Recording produced no file.");
      const durationMs = Math.max(1, Math.round(recorder.currentTime * 1000));
      const audioBytes = await new File(uri).bytes();

      const { messageCiphertext, mediaCiphertext } = await encryptOutgoingVoiceNote(
        token,
        conv,
        members,
        ownUserId,
        audioBytes,
        durationMs
      );
      const contentHash = hashBytesHex(mediaCiphertext);
      const { media_object_id, upload_url } = await messagingApi.requestMediaUpload(token, {
        contentHash,
        encryptedSizeBytes: mediaCiphertext.length,
        contentType: "audio/m4a",
      });
      await messagingApi.uploadEncryptedMedia(upload_url, "audio/m4a", mediaCiphertext);
      const sent = await messagingApi.sendMessage(token, conv.id, {
        ciphertext: messageCiphertext,
        contentType: "voice_note",
        clientMessageId: randomId(),
        mediaObjectId: media_object_id,
      });
      // Recover the same key/nonce a recipient would, from the message
      // that was just sent — `encryptOutgoingVoiceNote` doesn't hand the
      // one-time media key back directly, and this way there's exactly
      // one code path that turns "a voice note message" into playable
      // key material, for the sender's own optimistic row too.
      const voiceNote = await decryptIncomingVoiceNoteKey(token, conv, sent.sender_device_id, sent.ciphertext);
      setMessages((current) => [{ ...sent, plaintext: null, voiceNote }, ...current]);
    } catch {
      setError("Could not send that voice note.");
    } finally {
      setSendingVoiceNote(false);
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

  async function handleSetPinned(message: DecryptedMessage, value: boolean) {
    const token = tokenRef.current;
    if (!token) return;
    setOpenActionsFor(null);
    try {
      const updated = await messagingApi.setMessagePinned(token, message.id, value);
      setMessages((current) => current.map((m) => (m.id === message.id ? { ...m, pinned_at: updated.pinned_at } : m)));
      setPinnedMessage(value ? { ...message, pinned_at: updated.pinned_at } : null);
      if (!value) await refreshPinnedMessage();
    } catch {
      setError("Could not update that pin.");
    }
  }

  /** One active reaction message per (sender device, target message) —
   * the client enforces this by deleting its own prior reaction before
   * sending a new one, so counting non-deleted reaction messages by
   * emoji is accurate without any server-side aggregation. */
  const reactionsByTarget = useMemo(() => {
    const latestBySenderTarget = new Map<string, DecryptedMessage>();
    for (const m of messages) {
      if (m.content_type !== "reaction" || m.deleted_at || !m.reply_to_message_id || !m.sender_device_id) {
        continue;
      }
      const key = `${m.sender_device_id}:${m.reply_to_message_id}`;
      const existing = latestBySenderTarget.get(key);
      if (!existing || new Date(m.created_at) > new Date(existing.created_at)) {
        latestBySenderTarget.set(key, m);
      }
    }
    const map = new Map<string, { emoji: string; count: number; mine: boolean; myMessageId: string | null }[]>();
    for (const m of latestBySenderTarget.values()) {
      if (!m.plaintext || !m.reply_to_message_id) continue;
      const target = m.reply_to_message_id;
      const list = map.get(target) ?? [];
      const mine = m.sender_device_id === ownDeviceId;
      const existingEmoji = list.find((r) => r.emoji === m.plaintext);
      if (existingEmoji) {
        existingEmoji.count += 1;
        if (mine) {
          existingEmoji.mine = true;
          existingEmoji.myMessageId = m.id;
        }
      } else {
        list.push({ emoji: m.plaintext, count: 1, mine, myMessageId: mine ? m.id : null });
      }
      map.set(target, list);
    }
    return map;
  }, [messages, ownDeviceId]);

  async function handleReact(targetMessageId: string, emoji: string) {
    const token = tokenRef.current;
    const conv = conversation;
    setReactionPickerFor(null);
    setOpenActionsFor(null);
    if (!token || !conv || !ownUserId) return;
    const existingReactions = reactionsByTarget.get(targetMessageId) ?? [];
    const mine = existingReactions.find((r) => r.mine);
    try {
      if (mine?.myMessageId) {
        await messagingApi.deleteMessage(token, mine.myMessageId);
        setMessages((current) =>
          current.map((m) =>
            m.id === mine.myMessageId ? { ...m, plaintext: null, deleted_at: new Date().toISOString() } : m
          )
        );
        if (mine.emoji === emoji) return; // toggled off
      }
      const ciphertext = await encryptOutgoingMessage(token, conv, members, ownUserId, emoji);
      const sent = await messagingApi.sendMessage(token, conv.id, {
        ciphertext,
        contentType: "reaction",
        clientMessageId: randomId(),
        replyToMessageId: targetMessageId,
      });
      setMessages((current) => [{ ...sent, plaintext: emoji }, ...current]);
    } catch {
      setError("Could not update that reaction.");
    }
  }

  function handleForward(message: DecryptedMessage) {
    setOpenActionsFor(null);
    if (!message.plaintext) return;
    router.push({ pathname: "/messages/forward", params: { text: message.plaintext } });
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

      {pinnedMessage ? (
        <Pressable
          testID="chat-pinned-banner"
          onPress={() => handleSetPinned(pinnedMessage, false)}
          className="mb-2 flex-row items-center gap-2 rounded-lg bg-accent-muted px-3 py-2"
        >
          <Icon name="bell" size={14} color={colors.accent} />
          <Text className="flex-1 text-xs text-text-primary" numberOfLines={1}>
            {pinnedMessage.plaintext ?? "Pinned message"}
          </Text>
          <Text className="text-xs font-medium text-accent">Unpin</Text>
        </Pressable>
      ) : null}

      <FlatList
        className="flex-1"
        // `messagingApi.listMessages` returns newest-first (matches the
        // backend's own `ORDER BY created_at DESC`) — exactly what an
        // `inverted` FlatList wants at index 0 (rendered at the bottom,
        // the initial scroll position), so this is used as-is. Reaction
        // messages are real Message rows (content_type "reaction") but
        // render as pills on their target bubble, never as their own row.
        data={messages.filter((m) => m.content_type !== "reaction")}
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
                  className={`rounded-2xl px-4 py-2.5 ${isOwn ? "rounded-br-xs" : "rounded-bl-xs"} ${
                    isDeleted
                      ? "border border-dashed border-border bg-transparent"
                      : isOwn
                        ? "bg-accent"
                        : "border border-border bg-surface"
                  } ${item.pending ? "opacity-60" : ""}`}
                >
                  {!isDeleted && item.content_type === "voice_note" ? (
                    <VoiceNoteBubble
                      messageId={item.id}
                      mediaObjectId={item.media_object_id}
                      keyPayload={item.voiceNote}
                      isOwn={isOwn}
                      iconColor={isOwn ? "#FFFFFF" : colors.textPrimary}
                      textColor={isOwn ? "#FFFFFF" : colors.textSecondary}
                    />
                  ) : (
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
                  )}
                </View>
              )}

              {!isDeleted && (reactionsByTarget.get(item.id)?.length ?? 0) > 0 ? (
                <View className={`mt-1 flex-row flex-wrap gap-1 ${isOwn ? "self-end" : "self-start"}`}>
                  {reactionsByTarget.get(item.id)!.map((r) => (
                    <Pressable
                      key={r.emoji}
                      testID={`chat-reaction-pill-${item.id}-${r.emoji}`}
                      onPress={() => handleReact(item.id, r.emoji)}
                      className={`flex-row items-center gap-1 rounded-full border px-2 py-0.5 ${
                        r.mine ? "border-accent bg-accent-muted" : "border-border bg-surface"
                      }`}
                    >
                      <Text className="text-xs">{r.emoji}</Text>
                      {r.count > 1 ? (
                        <Text className="text-xs text-text-tertiary">{r.count}</Text>
                      ) : null}
                    </Pressable>
                  ))}
                </View>
              ) : null}

              <View className={`mt-1 flex-row items-center gap-1 ${isOwn ? "self-end" : "self-start"}`}>
                {item.is_forwarded && !isDeleted ? (
                  <Text className="text-xs italic text-text-tertiary">Forwarded ·</Text>
                ) : null}
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
                <View className="mt-1 gap-2 rounded-lg border border-border bg-surface px-3 py-2">
                  <View className="flex-row flex-wrap gap-3">
                    <Pressable
                      testID={`chat-react-${item.id}`}
                      onPress={() => setReactionPickerFor(reactionPickerFor === item.id ? null : item.id)}
                    >
                      <Text className="text-xs font-medium text-accent">React</Text>
                    </Pressable>
                    <Pressable
                      testID={`chat-reply-${item.id}`}
                      onPress={() => {
                        setReplyingTo(item);
                        setOpenActionsFor(null);
                      }}
                    >
                      <Text className="text-xs font-medium text-accent">Reply</Text>
                    </Pressable>
                    {item.content_type === "text" ? (
                      <Pressable testID={`chat-forward-${item.id}`} onPress={() => handleForward(item)}>
                        <Text className="text-xs font-medium text-accent">Forward</Text>
                      </Pressable>
                    ) : null}
                    <Pressable
                      testID={`chat-pin-${item.id}`}
                      onPress={() => handleSetPinned(item, item.pinned_at === null)}
                    >
                      <Text className="text-xs font-medium text-text-secondary">
                        {item.pinned_at ? "Unpin" : "Pin"}
                      </Text>
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
                  {reactionPickerFor === item.id ? (
                    <View className="flex-row gap-3 border-t border-border pt-2">
                      {REACTION_EMOJI.map((emoji) => (
                        <Pressable
                          key={emoji}
                          testID={`chat-reaction-pick-${item.id}-${emoji}`}
                          onPress={() => handleReact(item.id, emoji)}
                        >
                          <Text style={{ fontSize: 20 }}>{emoji}</Text>
                        </Pressable>
                      ))}
                    </View>
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
        {isRecording ? (
          <View className="flex-row items-center gap-3 border-t border-border pb-4 pt-3">
            <Pressable
              testID="chat-cancel-recording"
              onPress={handleCancelRecording}
              className="h-11 w-11 items-center justify-center rounded-full active:bg-surface-raised"
            >
              <Icon name="trash" size={18} color={colors.danger} />
            </Pressable>
            <View className="flex-1 flex-row items-center gap-2">
              <View className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: colors.danger }} />
              <Text className="text-sm text-text-primary">
                {Math.floor(recordingSeconds / 60)}:{(recordingSeconds % 60).toString().padStart(2, "0")}
              </Text>
            </View>
            <Pressable
              testID="chat-send-voice-note"
              onPress={handleSendVoiceNote}
              disabled={sendingVoiceNote}
              className="h-11 w-11 items-center justify-center rounded-full bg-accent disabled:opacity-50"
            >
              <Icon name="send" size={18} color="#FFFFFF" />
            </Pressable>
          </View>
        ) : (
          <View className="flex-row items-center gap-2 border-t border-border pb-4 pt-3">
            <TextInput
              testID="chat-input"
              value={draft}
              onChangeText={handleDraftChange}
              placeholder="Message"
              placeholderTextColor={colors.textTertiary}
              multiline
              className="flex-1 rounded-full border border-border bg-surface px-4 py-2.5 text-text-primary"
            />
            <Pressable
              testID="chat-send-button"
              onPress={draft.trim().length === 0 ? handleStartRecording : handleSend}
              disabled={sending}
              className="h-11 w-11 items-center justify-center rounded-full bg-accent disabled:opacity-50"
            >
              <Icon name={draft.trim().length === 0 ? "mic" : "send"} size={18} color="#FFFFFF" />
            </Pressable>
          </View>
        )}
      </KeyboardAvoidingView>
    </Screen>
  );
}
