import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { FlatList, KeyboardAvoidingView, Platform, Pressable, Text, TextInput, View } from "react-native";

import { Screen } from "../../components/Screen";
import { decryptIncomingMessage, encryptOutgoingMessage } from "../../lib/crypto/chat-crypto";
import { randomId } from "../../lib/id";
import { authApi } from "../../lib/api";
import {
  type Conversation,
  type ConversationMember,
  type Message,
  messagingApi,
} from "../../lib/messaging-api";
import { messagingSocket } from "../../lib/messaging-ws";
import { getAccessToken } from "../../lib/session";

interface DecryptedMessage extends Message {
  plaintext: string | null;
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

export default function ChatScreen() {
  const router = useRouter();
  const { conversationId } = useLocalSearchParams<{ conversationId: string }>();

  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [members, setMembers] = useState<ConversationMember[]>([]);
  const [ownUserId, setOwnUserId] = useState<string | null>(null);
  const [ownDeviceId, setOwnDeviceId] = useState<string | null>(null);
  const [messages, setMessages] = useState<DecryptedMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const tokenRef = useRef<string | null>(null);

  const decryptAll = useCallback(
    async (token: string, conv: Conversation, raw: Message[]): Promise<DecryptedMessage[]> => {
      return Promise.all(
        raw.map(async (message) => ({
          ...message,
          plaintext: await decryptIncomingMessage(
            token,
            conv,
            message.sender_device_id,
            message.ciphertext
          ),
        }))
      );
    },
    []
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
      // Messages only carry `sender_device_id` (the backend infers the
      // sender's own device from their access token) — comparing
      // against this device tells a bubble apart as "mine" or theirs.
      setOwnDeviceId(await messagingApi.getPrimaryDevice(token, me.id));

      const rawMessages = await messagingApi.listMessages(token, conversationId);
      setMessages(await decryptAll(token, conv, rawMessages));
      setError(null);
    } catch {
      setError("Could not load this conversation.");
    }
  }, [conversationId, router, decryptAll]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    return messagingSocket.onEvent((event) => {
      if (event.type === "message.new" && event.conversation_id === conversationId) {
        load();
      }
    });
  }, [conversationId, load]);

  async function handleSend() {
    const token = tokenRef.current;
    if (!token || !conversation || !ownUserId || draft.trim().length === 0) return;
    const text = draft.trim();
    setDraft("");
    setSending(true);
    try {
      const ciphertext = await encryptOutgoingMessage(
        token,
        conversation,
        members,
        ownUserId,
        text
      );
      await messagingApi.sendMessage(token, conversation.id, {
        ciphertext,
        contentType: "text",
        clientMessageId: randomId(),
      });
      await load();
    } catch {
      setError("Could not send that message.");
      setDraft(text);
    } finally {
      setSending(false);
    }
  }

  const title =
    conversation?.type === "group"
      ? (conversation.title ?? members.map((m) => m.display_name).join(", "))
      : (members.find((m) => m.user_id !== ownUserId)?.display_name ?? "Chat");

  return (
    <Screen scroll={false}>
      <View className="mb-3 mt-8 flex-row items-center gap-3">
        <Pressable testID="chat-back-button" onPress={() => router.back()} className="p-1">
          <Text className="text-xl text-accent">‹</Text>
        </Pressable>
        <Text className="flex-1 text-xl font-semibold text-text-primary" numberOfLines={1}>
          {title}
        </Text>
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
        renderItem={({ item }) => {
          const isOwn = item.sender_device_id !== null && item.sender_device_id === ownDeviceId;
          return (
            <View className={`mb-2 max-w-[80%] ${isOwn ? "self-end" : "self-start"}`}>
              <View
                className={`rounded-2xl px-4 py-2 ${
                  isOwn ? "bg-accent" : "border border-border bg-surface"
                }`}
              >
                <Text className={isOwn ? "text-background" : "text-text-primary"}>
                  {item.plaintext ?? "🔒 Couldn't decrypt this message"}
                </Text>
              </View>
              <Text className="mt-1 text-xs text-text-tertiary">
                {formatTime(item.created_at)}
              </Text>
            </View>
          );
        }}
      />

      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <View className="flex-row items-center gap-2 border-t border-border pb-4 pt-3">
          <TextInput
            testID="chat-input"
            value={draft}
            onChangeText={setDraft}
            placeholder="Message"
            placeholderTextColor="#6E6E85"
            multiline
            className="flex-1 rounded-2xl border border-border bg-surface px-4 py-2 text-text-primary"
          />
          <Pressable
            testID="chat-send-button"
            onPress={handleSend}
            disabled={sending || draft.trim().length === 0}
            className="h-10 w-10 items-center justify-center rounded-full bg-accent disabled:opacity-50"
          >
            <Text className="text-lg text-background">↑</Text>
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </Screen>
  );
}
