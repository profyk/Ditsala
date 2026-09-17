import { dark } from "@ditsala/ui-tokens";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { FlatList, Pressable, Text, View } from "react-native";

import { Avatar } from "../../components/Avatar";
import { Icon } from "../../components/Icon";
import { TabScreen } from "../../components/TabScreen";
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
    <TabScreen>
      <Text className="mb-6 mt-4 text-2xl font-bold text-text-primary">Messages</Text>

      {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}

      <FlatList
        scrollEnabled={false}
        data={rows}
        keyExtractor={(item) => item.conversation.id}
        renderItem={({ item }) => (
          <Pressable
            testID={`conversation-row-${item.conversation.id}`}
            onPress={() => router.push(`/messages/${item.conversation.id}`)}
            className="mb-2 flex-row items-center gap-3 rounded-xl border border-border bg-surface p-3 active:bg-surface-raised"
          >
            <Avatar id={item.conversation.id} name={item.title} imageUrl={item.avatarUrl} size={48} />
            <View className="flex-1">
              <Text className="text-base font-semibold text-text-primary" numberOfLines={1}>
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
            <View className="items-center rounded-xl border border-dashed border-border py-12">
              <View
                className="mb-3 h-14 w-14 items-center justify-center rounded-full"
                style={{ backgroundColor: dark.accentMuted }}
              >
                <Icon name="messages" size={26} color={dark.accent} />
              </View>
              <Text className="mb-1 text-base font-semibold text-text-primary">
                No conversations yet
              </Text>
              <Text className="px-8 text-center text-sm text-text-tertiary">
                Message someone from your Circle to start one.
              </Text>
            </View>
          ) : null
        }
      />
    </TabScreen>
  );
}
