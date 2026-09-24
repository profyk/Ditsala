import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { FlatList, Pressable, RefreshControl, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { Avatar } from "../../components/Avatar";
import { Icon } from "../../components/Icon";
import { TabBar } from "../../components/TabBar";
import { authApi } from "../../lib/api";
import { decryptIncomingMessage } from "../../lib/crypto/chat-crypto";
import { type Conversation, type ConversationMember, messagingApi } from "../../lib/messaging-api";
import { getAccessToken } from "../../lib/session";
import { useTheme } from "../../lib/theme-context";

/**
 * "Messages" — the conversation list. Previously nested a FlatList
 * inside TabScreen's own ScrollView with `scrollEnabled={false}` to
 * avoid React Native's well-known "VirtualizedList inside ScrollView"
 * warning — but that leaves the FlatList's own virtualization with no
 * scroll events to react to, so anyone with more conversations than
 * fit on one screen (past `initialNumToRender`) could lose rows
 * entirely off the bottom with no way to reach them. Rebuilt with its
 * own layout: the FlatList itself scrolls, TabScreen isn't used here.
 */

interface ConversationRow {
  conversation: Conversation;
  title: string;
  avatarUrl: string | null;
  preview: string;
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

function previewFor(contentType: string, plaintext: string | null): string {
  if (contentType === "media") return "Photo";
  if (contentType === "voice_note") return "Voice message";
  if (contentType === "reaction") return "Reaction";
  if (contentType === "system") return plaintext ?? "System message";
  return plaintext ?? "New message";
}

export default function MessagesList() {
  const router = useRouter();
  const { colors } = useTheme();
  const [rows, setRows] = useState<ConversationRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [newMenuOpen, setNewMenuOpen] = useState(false);
  const [openActionsFor, setOpenActionsFor] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);

  const load = useCallback(
    async (isRefresh: boolean) => {
      const accessToken = await getAccessToken();
      if (!accessToken) {
        router.replace("/");
        return;
      }
      setToken(accessToken);
      if (!isRefresh) setLoading(true);
      try {
        const me = await authApi.getMe(accessToken);
        const conversations = await messagingApi.listConversations(accessToken);
        const sorted = [...conversations].sort((a, b) => {
          if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
          const aTime = a.last_message_at ? new Date(a.last_message_at).getTime() : 0;
          const bTime = b.last_message_at ? new Date(b.last_message_at).getTime() : 0;
          return bTime - aTime;
        });

        const withDisplay = await Promise.all(
          sorted.map(async (conversation): Promise<ConversationRow> => {
            let members: ConversationMember[] = [];
            try {
              members = await messagingApi.listConversationMembers(
                accessToken,
                conversation.id
              );
            } catch {
              // A conversation we can't enrich (e.g. race with membership
              // change) still deserves a row — just less display detail.
            }

            let preview = "No messages yet";
            if (conversation.last_message_at) {
              try {
                const [latest] = await messagingApi.listMessages(accessToken, conversation.id, {
                  limit: 1,
                });
                if (latest?.deleted_at) {
                  preview = "This message was deleted";
                } else if (latest) {
                  // Real, on-device decryption for the preview too — the
                  // server never sees plaintext, so there's no other way
                  // to show "what was the last message" honestly.
                  const plaintext = await decryptIncomingMessage(
                    accessToken,
                    conversation,
                    latest.sender_device_id,
                    latest.ciphertext
                  );
                  preview = previewFor(latest.content_type, plaintext);
                }
              } catch {
                // Preview is a nice-to-have — a fetch/decrypt failure
                // shouldn't stop the row from showing at all.
              }
            }

            if (conversation.type === "group") {
              return {
                conversation,
                title: conversation.title ?? members.map((m) => m.display_name).join(", "),
                avatarUrl: null,
                preview,
              };
            }
            const other = members.find((m) => m.user_id !== me.id);
            return {
              conversation,
              title: other?.display_name ?? "Direct message",
              avatarUrl: other?.avatar_url ?? null,
              preview,
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

  async function handleTogglePin(row: ConversationRow) {
    if (!token) return;
    setBusyId(row.conversation.id);
    setOpenActionsFor(null);
    try {
      await messagingApi.setPinned(token, row.conversation.id, !row.conversation.pinned);
      await load(true);
    } catch {
      setError("Could not update that conversation.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleToggleMute(row: ConversationRow) {
    if (!token) return;
    setBusyId(row.conversation.id);
    setOpenActionsFor(null);
    try {
      const isMuted = row.conversation.muted_until !== null;
      await messagingApi.setMuted(
        token,
        row.conversation.id,
        isMuted ? null : new Date("2099-01-01T00:00:00Z").toISOString()
      );
      await load(true);
    } catch {
      setError("Could not update that conversation.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleToggleArchive(row: ConversationRow) {
    if (!token) return;
    setBusyId(row.conversation.id);
    setOpenActionsFor(null);
    try {
      await messagingApi.setArchived(token, row.conversation.id, !row.conversation.archived);
      await load(true);
    } catch {
      setError("Could not update that conversation.");
    } finally {
      setBusyId(null);
    }
  }

  const archivedRows = rows.filter((r) => r.conversation.archived);
  const visibleRows = showArchived ? rows : rows.filter((r) => !r.conversation.archived);

  return (
    <SafeAreaView className="flex-1 bg-background" edges={["top"]}>
      <View className="flex-1 px-6">
        <View className="mb-2 mt-4 flex-row items-center justify-between">
          <Text className="text-2xl font-bold text-text-primary">Messages</Text>
          <Pressable
            testID="messages-new-button"
            onPress={() => setNewMenuOpen((v) => !v)}
            className="h-10 w-10 items-center justify-center rounded-full bg-accent"
          >
            <Icon name="plus" size={18} color="#FFFFFF" />
          </Pressable>
        </View>

        {newMenuOpen ? (
          <View className="mb-4 overflow-hidden rounded-xl border border-border bg-surface">
            <Pressable
              testID="messages-new-direct"
              onPress={() => {
                setNewMenuOpen(false);
                router.push("/circle");
              }}
              className="border-b border-border px-4 py-3 active:bg-surface-raised"
            >
              <Text className="text-sm font-medium text-text-primary">New message</Text>
              <Text className="text-xs text-text-tertiary">Message someone from your Circle</Text>
            </Pressable>
            <Pressable
              testID="messages-new-group"
              onPress={() => {
                setNewMenuOpen(false);
                router.push("/messages/new-group");
              }}
              className="px-4 py-3 active:bg-surface-raised"
            >
              <Text className="text-sm font-medium text-text-primary">New group</Text>
              <Text className="text-xs text-text-tertiary">Start a conversation with several people</Text>
            </Pressable>
          </View>
        ) : null}

        {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}

        <FlatList
          data={visibleRows}
          keyExtractor={(item) => item.conversation.id}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={handleRefresh} tintColor={colors.accent} />
          }
          renderItem={({ item }) => {
            const isMuted = item.conversation.muted_until !== null;
            const actionsOpen = openActionsFor === item.conversation.id;
            const isBusy = busyId === item.conversation.id;
            return (
              <View className="mb-2 overflow-hidden rounded-xl border border-border bg-surface">
                <Pressable
                  testID={`conversation-row-${item.conversation.id}`}
                  onPress={() => router.push(`/messages/${item.conversation.id}`)}
                  onLongPress={() => setOpenActionsFor(actionsOpen ? null : item.conversation.id)}
                  className="flex-row items-center gap-3 p-3 active:bg-surface-raised"
                >
                  <Avatar
                    id={item.conversation.id}
                    name={item.title}
                    imageUrl={item.avatarUrl}
                    size={48}
                  />
                  <View className="flex-1">
                    <View className="flex-row items-center gap-1.5">
                      {item.conversation.pinned ? (
                        <Icon name="chevron-right" size={10} color={colors.textTertiary} />
                      ) : null}
                      <Text
                        className="flex-1 text-base font-semibold text-text-primary"
                        numberOfLines={1}
                      >
                        {item.title}
                      </Text>
                    </View>
                    <Text className="text-sm text-text-tertiary" numberOfLines={1}>
                      {item.preview}
                    </Text>
                  </View>
                  <View className="items-end gap-1">
                    <Text className="text-xs text-text-tertiary">
                      {formatWhen(item.conversation.last_message_at)}
                    </Text>
                    {isMuted ? <Icon name="bell" size={12} color={colors.textTertiary} /> : null}
                  </View>
                  <Pressable
                    testID={`conversation-more-${item.conversation.id}`}
                    onPress={() => setOpenActionsFor(actionsOpen ? null : item.conversation.id)}
                    className="p-1"
                  >
                    <Icon name="more" size={16} color={colors.textTertiary} />
                  </Pressable>
                </Pressable>

                {actionsOpen ? (
                  <View className="flex-row gap-2 border-t border-border px-3 py-2">
                    <Pressable
                      testID={`conversation-pin-${item.conversation.id}`}
                      disabled={isBusy}
                      onPress={() => handleTogglePin(item)}
                      className="flex-1 items-center rounded-lg py-2 active:bg-surface-raised disabled:opacity-50"
                    >
                      <Text className="text-xs font-medium text-text-secondary">
                        {item.conversation.pinned ? "Unpin" : "Pin"}
                      </Text>
                    </Pressable>
                    <Pressable
                      testID={`conversation-mute-${item.conversation.id}`}
                      disabled={isBusy}
                      onPress={() => handleToggleMute(item)}
                      className="flex-1 items-center rounded-lg py-2 active:bg-surface-raised disabled:opacity-50"
                    >
                      <Text className="text-xs font-medium text-text-secondary">
                        {isMuted ? "Unmute" : "Mute"}
                      </Text>
                    </Pressable>
                    <Pressable
                      testID={`conversation-archive-${item.conversation.id}`}
                      disabled={isBusy}
                      onPress={() => handleToggleArchive(item)}
                      className="flex-1 items-center rounded-lg py-2 active:bg-surface-raised disabled:opacity-50"
                    >
                      <Text className="text-xs font-medium text-danger">
                        {item.conversation.archived ? "Unarchive" : "Archive"}
                      </Text>
                    </Pressable>
                  </View>
                ) : null}
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
                  <Icon name="messages" size={26} color={colors.accent} />
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
          ListFooterComponent={
            archivedRows.length > 0 ? (
              <Pressable
                testID="messages-toggle-archived"
                onPress={() => setShowArchived((v) => !v)}
                className="items-center py-3"
              >
                <Text className="text-sm font-medium text-accent">
                  {showArchived
                    ? "Hide archived"
                    : `Show archived (${archivedRows.length})`}
                </Text>
              </Pressable>
            ) : null
          }
        />
      </View>
      <TabBar />
    </SafeAreaView>
  );
}
