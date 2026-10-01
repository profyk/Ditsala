import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { FlatList, Pressable, RefreshControl, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { Avatar } from "../../components/Avatar";
import { Icon } from "../../components/Icon";
import { TabBar } from "../../components/TabBar";
import { authApi } from "../../lib/api";
import { callsApi, type Call } from "../../lib/calls-api";
import { useCall } from "../../lib/call-context";
import { messagingApi } from "../../lib/messaging-api";
import { getAccessToken } from "../../lib/session";
import { useTheme } from "../../lib/theme-context";

interface CallRow {
  call: Call;
  otherUserId: string | null;
  title: string;
  avatarUrl: string | null;
  outgoing: boolean;
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

function formatDuration(startedAt: string | null, endedAt: string | null): string | null {
  if (!startedAt || !endedAt) return null;
  const seconds = Math.max(0, Math.round((new Date(endedAt).getTime() - new Date(startedAt).getTime()) / 1000));
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

/**
 * Call history — new screen, no backend work needed: `GET /calls`
 * (`callsApi.listCalls`) already existed and was already fully typed and
 * tested, just never had a mobile screen calling it. `CallResponse` has
 * no "other participant" field (calls are always `direct`-conversation
 * only), so the other party is resolved the same way `messages/index.tsx`
 * already resolves a DM's other member — via `listConversationMembers`,
 * memoized per conversation so repeat calls with the same contact don't
 * refetch.
 */
export default function CallsList() {
  const router = useRouter();
  const { colors } = useTheme();
  const { startCall } = useCall();
  const [rows, setRows] = useState<CallRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [callingId, setCallingId] = useState<string | null>(null);

  const load = useCallback(
    async (isRefresh: boolean) => {
      const accessToken = await getAccessToken();
      if (!accessToken) {
        router.replace("/");
        return;
      }
      if (!isRefresh) setLoading(true);
      try {
        const me = await authApi.getMe(accessToken);
        const calls = await callsApi.listCalls(accessToken);
        const sorted = [...calls].sort((a, b) => {
          const aTime = a.started_at ? new Date(a.started_at).getTime() : 0;
          const bTime = b.started_at ? new Date(b.started_at).getTime() : 0;
          return bTime - aTime;
        });

        const memberCache = new Map<string, Awaited<ReturnType<typeof messagingApi.listConversationMembers>>>();
        const withDisplay = await Promise.all(
          sorted.map(async (call): Promise<CallRow> => {
            if (!call.conversation_id) {
              return { call, otherUserId: null, title: "Unknown", avatarUrl: null, outgoing: call.initiator_user_id === me.id };
            }
            let members = memberCache.get(call.conversation_id);
            if (!members) {
              try {
                members = await messagingApi.listConversationMembers(accessToken, call.conversation_id);
                memberCache.set(call.conversation_id, members);
              } catch {
                members = [];
              }
            }
            const other = members.find((m) => m.user_id !== me.id);
            return {
              call,
              otherUserId: other?.user_id ?? null,
              title: other?.display_name ?? "Unknown",
              avatarUrl: other?.avatar_url ?? null,
              outgoing: call.initiator_user_id === me.id,
            };
          })
        );
        setRows(withDisplay);
        setError(null);
      } catch {
        setError("Could not load your calls.");
      } finally {
        setLoading(false);
      }
    },
    [router]
  );

  useFocusEffect(
    useCallback(() => {
      load(false);
    }, [load])
  );

  async function handleRefresh() {
    setRefreshing(true);
    await load(true);
    setRefreshing(false);
  }

  async function handleCallBack(row: CallRow, callType: "voice" | "video") {
    if (!row.call.conversation_id) return;
    setCallingId(row.call.id);
    try {
      await startCall(row.call.conversation_id, callType);
    } catch {
      setError("Could not start the call.");
    } finally {
      setCallingId(null);
    }
  }

  return (
    <SafeAreaView className="flex-1 bg-background" edges={["top"]}>
      <View className="flex-1 px-6">
        <View className="mb-4 mt-4">
          <Text className="text-2xl font-bold text-text-primary">Calls</Text>
        </View>

        {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}

        <FlatList
          data={rows}
          keyExtractor={(item) => item.call.id}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={handleRefresh} tintColor={colors.accent} />
          }
          renderItem={({ item }) => {
            const duration = formatDuration(item.call.started_at, item.call.ended_at);
            const isMissedOrDeclined = item.call.status === "missed" || item.call.status === "declined";
            let statusLabel: string;
            if (item.call.status === "missed") {
              statusLabel = item.outgoing ? "No answer" : "Missed call";
            } else if (item.call.status === "declined") {
              statusLabel = item.outgoing ? "Call declined" : "Declined";
            } else if (duration) {
              statusLabel = duration;
            } else if (item.call.status === "ringing") {
              statusLabel = "Ringing…";
            } else {
              statusLabel = "Ongoing";
            }
            const isBusy = callingId === item.call.id;
            return (
              <View className="flex-row items-center gap-3 border-b border-border py-3">
                <Avatar id={item.otherUserId ?? item.call.id} name={item.title} imageUrl={item.avatarUrl} size={48} />
                <View className="flex-1">
                  <Text className="text-base font-semibold text-text-primary" numberOfLines={1}>
                    {item.title}
                  </Text>
                  <View className="flex-row items-center gap-1.5">
                    <Icon
                      name={item.call.type === "video" ? "video" : "phone"}
                      size={12}
                      color={isMissedOrDeclined ? colors.danger : colors.textTertiary}
                    />
                    <Text
                      className="text-sm"
                      style={{ color: isMissedOrDeclined ? colors.danger : colors.textTertiary }}
                      numberOfLines={1}
                    >
                      {statusLabel}
                    </Text>
                  </View>
                </View>
                <View className="items-end gap-2">
                  <Text className="text-xs text-text-tertiary">{formatWhen(item.call.started_at)}</Text>
                  {item.call.conversation_id ? (
                    <View className="flex-row gap-3">
                      <Pressable
                        testID={`call-back-voice-${item.call.id}`}
                        disabled={isBusy}
                        onPress={() => handleCallBack(item, "voice")}
                        className="h-8 w-8 items-center justify-center rounded-full bg-accent-muted disabled:opacity-50"
                      >
                        <Icon name="phone" size={14} color={colors.accent} />
                      </Pressable>
                      <Pressable
                        testID={`call-back-video-${item.call.id}`}
                        disabled={isBusy}
                        onPress={() => handleCallBack(item, "video")}
                        className="h-8 w-8 items-center justify-center rounded-full bg-accent-muted disabled:opacity-50"
                      >
                        <Icon name="video" size={14} color={colors.accent} />
                      </Pressable>
                    </View>
                  ) : null}
                </View>
              </View>
            );
          }}
          ListEmptyComponent={
            !loading ? (
              <View className="items-center rounded-xl border border-dashed border-border py-12">
                <View
                  className="mb-3 h-14 w-14 items-center justify-center rounded-full"
                  style={{ backgroundColor: colors.accentMuted }}
                >
                  <Icon name="phone" size={26} color={colors.accent} />
                </View>
                <Text className="mb-1 text-base font-semibold text-text-primary">No calls yet</Text>
                <Text className="px-8 text-center text-sm text-text-tertiary">
                  Call someone from your Circle to get started.
                </Text>
              </View>
            ) : null
          }
        />

        <Pressable
          testID="calls-new-button"
          onPress={() => router.push("/circle")}
          className="absolute bottom-6 right-6 h-14 w-14 items-center justify-center rounded-full bg-accent shadow-lg"
        >
          <Icon name="plus" size={24} color="#FFFFFF" />
        </Pressable>
      </View>
      <TabBar />
    </SafeAreaView>
  );
}
