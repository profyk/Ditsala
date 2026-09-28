import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, FlatList, Pressable, Text, View } from "react-native";

import { Avatar } from "../../components/Avatar";
import { Icon } from "../../components/Icon";
import { Screen } from "../../components/Screen";
import { authApi } from "../../lib/api";
import { encryptOutgoingMessage } from "../../lib/crypto/chat-crypto";
import { randomId } from "../../lib/id";
import { type Conversation, messagingApi } from "../../lib/messaging-api";
import { getAccessToken } from "../../lib/session";
import { useTheme } from "../../lib/theme-context";

interface Row {
  conversation: Conversation;
  title: string;
  avatarUrl: string | null;
}

/**
 * Forwarding a text message — a real, client-side operation, not a
 * server copy: the sender already holds the plaintext (passed in via
 * the `text` route param from the chat screen), and this screen just
 * re-encrypts it fresh for whichever conversation gets picked, since
 * one conversation's Sender Key can never decrypt another's ciphertext.
 * Scoped to text messages for this pass — forwarding media/voice notes
 * would also need to re-upload the encrypted blob under a new object,
 * a separate, larger piece of work not attempted here.
 */
export default function ForwardMessage() {
  const router = useRouter();
  const { colors } = useTheme();
  const { text } = useLocalSearchParams<{ text: string }>();
  const [ownUserId, setOwnUserId] = useState<string | null>(null);
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sendingTo, setSendingTo] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    const token = await getAccessToken();
    if (!token) {
      router.replace("/");
      return;
    }
    try {
      const me = await authApi.getMe(token);
      setOwnUserId(me.id);
      const conversations = await messagingApi.listConversations(token);
      const withDisplay = await Promise.all(
        conversations.map(async (conversation): Promise<Row> => {
          const members = await messagingApi.listConversationMembers(token, conversation.id);
          if (conversation.type === "group") {
            return {
              conversation,
              title: conversation.title ?? members.map((m) => m.display_name).join(", "),
              avatarUrl: null,
            };
          }
          const other = members.find((m) => m.user_id !== me.id);
          return {
            conversation,
            title: other?.display_name ?? "Direct message",
            avatarUrl: other?.avatar_url ?? null,
          };
        })
      );
      setRows(withDisplay);
    } catch {
      setError("Could not load your conversations.");
    }
  }, [router]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  async function handleForwardTo(row: Row) {
    const token = await getAccessToken();
    if (!token || !ownUserId || !text) return;
    setSendingTo(row.conversation.id);
    setError(null);
    try {
      const members = await messagingApi.listConversationMembers(token, row.conversation.id);
      const ciphertext = await encryptOutgoingMessage(token, row.conversation, members, ownUserId, text);
      await messagingApi.sendMessage(token, row.conversation.id, {
        ciphertext,
        contentType: "text",
        clientMessageId: randomId(),
        isForwarded: true,
      });
      setSentTo((current) => new Set(current).add(row.conversation.id));
    } catch {
      setError("Could not forward to that conversation.");
    } finally {
      setSendingTo(null);
    }
  }

  return (
    <Screen scroll={false}>
      <View className="mb-4 mt-8 flex-row items-center gap-3">
        <Pressable
          testID="forward-back-button"
          onPress={() => router.back()}
          className="h-9 w-9 items-center justify-center rounded-full active:bg-surface-raised"
        >
          <Icon name="chevron-left" size={20} color={colors.textPrimary} />
        </Pressable>
        <Text className="text-lg font-bold text-text-primary">Forward to…</Text>
      </View>

      {error ? <Text className="mb-3 text-sm text-danger">{error}</Text> : null}

      {rows === null ? (
        <ActivityIndicator color={colors.accent} />
      ) : (
        <FlatList
          className="flex-1"
          data={rows}
          keyExtractor={(item) => item.conversation.id}
          renderItem={({ item }) => {
            const sent = sentTo.has(item.conversation.id);
            const sending = sendingTo === item.conversation.id;
            return (
              <Pressable
                testID={`forward-target-${item.conversation.id}`}
                onPress={() => handleForwardTo(item)}
                disabled={sending || sent}
                className="mb-2 flex-row items-center gap-3 rounded-xl border border-border bg-surface p-3 active:bg-surface-raised disabled:opacity-60"
              >
                <Avatar id={item.conversation.id} name={item.title} imageUrl={item.avatarUrl} size={40} />
                <Text className="flex-1 text-base text-text-primary" numberOfLines={1}>
                  {item.title}
                </Text>
                {sending ? (
                  <ActivityIndicator color={colors.accent} />
                ) : sent ? (
                  <Icon name="check" size={18} color={colors.accent} />
                ) : null}
              </Pressable>
            );
          }}
        />
      )}
    </Screen>
  );
}
