import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { FlatList, Image, Pressable, Text, View } from "react-native";

import { Screen } from "../../components/Screen";
import { authApi } from "../../lib/api";
import { type Conversation, type ConversationMember, messagingApi } from "../../lib/messaging-api";
import { getAccessToken } from "../../lib/session";

interface ConversationRow {
  conversation: Conversation;
  title: string;
  avatarUrl: string | null;
}

function formatWhen(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  return sameDay
    ? date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
    : date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export default function MessagesList() {
  const router = useRouter();
  const [rows, setRows] = useState<ConversationRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    const token = await getAccessToken();
    if (!token) {
      router.replace("/");
      return;
    }
    try {
      const me = await authApi.getMe(token);
      const conversations = await messagingApi.listConversations(token);
      const sorted = [...conversations].sort((a, b) => {
        const aTime = a.last_message_at ? new Date(a.last_message_at).getTime() : 0;
        const bTime = b.last_message_at ? new Date(b.last_message_at).getTime() : 0;
        return bTime - aTime;
      });

      const withDisplay = await Promise.all(
        sorted.map(async (conversation): Promise<ConversationRow> => {
          let members: ConversationMember[] = [];
          try {
            members = await messagingApi.listConversationMembers(token, conversation.id);
          } catch {
            // A conversation we can't enrich (e.g. race with membership
            // change) still deserves a row — just less display detail.
          }
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
      setError(null);
    } catch {
      setError("Could not load your messages.");
    } finally {
      setLoading(false);
    }
  }, [router]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  return (
    <Screen>
      <Text className="mb-6 mt-8 text-3xl font-semibold text-text-primary">Messages</Text>

      {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}

      <FlatList
        data={rows}
        keyExtractor={(item) => item.conversation.id}
        renderItem={({ item }) => (
          <Pressable
            testID={`conversation-row-${item.conversation.id}`}
            onPress={() => router.push(`/messages/${item.conversation.id}`)}
            className="mb-2 flex-row items-center gap-3 rounded-lg border border-border bg-surface p-3 active:bg-surface-raised"
          >
            <View className="h-12 w-12 items-center justify-center overflow-hidden rounded-full bg-surface-raised">
              {item.avatarUrl ? (
                <Image source={{ uri: item.avatarUrl }} className="h-12 w-12" />
              ) : (
                <Text className="text-lg font-semibold text-text-tertiary">
                  {item.title.charAt(0).toUpperCase()}
                </Text>
              )}
            </View>
            <View className="flex-1">
              <Text className="text-base font-medium text-text-primary" numberOfLines={1}>
                {item.title}
              </Text>
              <Text className="text-sm text-text-tertiary">
                {item.conversation.last_message_at ? "Tap to view" : "No messages yet"}
              </Text>
            </View>
            <Text className="text-xs text-text-tertiary">
              {formatWhen(item.conversation.last_message_at)}
            </Text>
          </Pressable>
        )}
        ListEmptyComponent={
          !loading ? (
            <Text className="text-sm text-text-tertiary">
              No conversations yet — message someone from your Circle to start one.
            </Text>
          ) : null
        }
      />
    </Screen>
  );
}
