import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, Text, TextInput, View } from "react-native";

import { Avatar } from "../../components/Avatar";
import { Icon } from "../../components/Icon";
import { Screen } from "../../components/Screen";
import { authApi } from "../../lib/api";
import { circleApi, type Contact } from "../../lib/circle-api";
import { type ConversationMember, messagingApi } from "../../lib/messaging-api";
import { getAccessToken } from "../../lib/session";
import { useTheme } from "../../lib/theme-context";

/**
 * Group info/settings — member management (add/remove/promote/demote)
 * and rename, none of which had a mobile screen calling them before
 * this pass (add/remove/promote-admin endpoints didn't even exist
 * server-side; rename_group_conversation existed but had zero UI
 * callers, same class of gap "New group" itself closed for creation).
 */
export default function GroupInfo() {
  const router = useRouter();
  const { colors } = useTheme();
  const { conversationId } = useLocalSearchParams<{ conversationId: string }>();

  const [ownUserId, setOwnUserId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [editingTitle, setEditingTitle] = useState(false);
  const [members, setMembers] = useState<ConversationMember[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyUserId, setBusyUserId] = useState<string | null>(null);
  const [addingMember, setAddingMember] = useState(false);
  const [candidates, setCandidates] = useState<Contact[] | null>(null);

  const load = useCallback(async () => {
    const token = await getAccessToken();
    if (!token || !conversationId) {
      router.replace("/");
      return;
    }
    try {
      const [me, conversations, memberList] = await Promise.all([
        authApi.getMe(token),
        messagingApi.listConversations(token),
        messagingApi.listConversationMembers(token, conversationId),
      ]);
      setOwnUserId(me.id);
      const conv = conversations.find((c) => c.id === conversationId);
      setTitle(conv?.title ?? "");
      setMembers(memberList);
    } catch {
      setError("Could not load this group.");
    }
  }, [conversationId, router]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  const ownRole = members?.find((m) => m.user_id === ownUserId)?.role;
  const isAdmin = ownRole === "admin";

  async function handleSaveTitle() {
    const token = await getAccessToken();
    if (!token || !conversationId || title.trim().length === 0) return;
    try {
      await messagingApi.renameGroupConversation(token, conversationId, title.trim());
      setEditingTitle(false);
    } catch {
      setError("Could not rename this group.");
    }
  }

  async function handleSetRole(userId: string, role: "member" | "admin") {
    const token = await getAccessToken();
    if (!token || !conversationId) return;
    setBusyUserId(userId);
    try {
      await messagingApi.setMemberRole(token, conversationId, userId, role);
      await load();
    } catch {
      setError("Could not update that member's role.");
    } finally {
      setBusyUserId(null);
    }
  }

  async function handleRemove(userId: string) {
    const token = await getAccessToken();
    if (!token || !conversationId) return;
    setBusyUserId(userId);
    try {
      await messagingApi.removeGroupMember(token, conversationId, userId);
      if (userId === ownUserId) {
        router.replace("/messages");
        return;
      }
      await load();
    } catch {
      setError("Could not remove that member.");
    } finally {
      setBusyUserId(null);
    }
  }

  async function handleOpenAddMember() {
    setAddingMember(true);
    const token = await getAccessToken();
    if (!token) return;
    try {
      const all = await circleApi.listContacts(token);
      const memberIds = new Set((members ?? []).map((m) => m.user_id));
      setCandidates(
        all.filter((c) => (c.tier === "verified" || c.tier === "trusted") && !memberIds.has(c.contact_user_id))
      );
    } catch {
      setError("Could not load your Circle.");
    }
  }

  async function handleAddMember(userId: string) {
    const token = await getAccessToken();
    if (!token || !conversationId) return;
    setBusyUserId(userId);
    try {
      await messagingApi.addGroupMember(token, conversationId, userId);
      setAddingMember(false);
      setCandidates(null);
      await load();
    } catch {
      setError("Could not add that member.");
    } finally {
      setBusyUserId(null);
    }
  }

  return (
    <Screen scroll={false}>
      <View className="mb-4 mt-8 flex-row items-center gap-3">
        <Pressable
          testID="group-info-back-button"
          onPress={() => router.back()}
          className="h-9 w-9 items-center justify-center rounded-full active:bg-surface-raised"
        >
          <Icon name="chevron-left" size={20} color={colors.textPrimary} />
        </Pressable>
        <Text className="text-lg font-bold text-text-primary">Group info</Text>
      </View>

      {error ? <Text className="mb-3 text-sm text-danger">{error}</Text> : null}

      {members === null ? (
        <ActivityIndicator color={colors.accent} />
      ) : (
        <View className="flex-1">
          <View className="mb-4 flex-row items-center gap-2">
            {editingTitle ? (
              <>
                <TextInput
                  testID="group-info-title-input"
                  value={title}
                  onChangeText={setTitle}
                  autoFocus
                  className="flex-1 rounded-xl border border-border bg-surface px-4 py-3 text-text-primary"
                />
                <Pressable testID="group-info-save-title" onPress={handleSaveTitle}>
                  <Text className="text-sm font-semibold text-accent">Save</Text>
                </Pressable>
              </>
            ) : (
              <>
                <Text className="flex-1 text-xl font-bold text-text-primary">{title || "Group"}</Text>
                {isAdmin ? (
                  <Pressable testID="group-info-edit-title" onPress={() => setEditingTitle(true)}>
                    <Icon name="edit" size={18} color={colors.accent} />
                  </Pressable>
                ) : null}
              </>
            )}
          </View>

          <View className="mb-2 flex-row items-center justify-between">
            <Text className="text-xs font-medium uppercase tracking-widest text-text-tertiary">
              {members.length} members
            </Text>
            {isAdmin ? (
              <Pressable testID="group-info-add-member" onPress={handleOpenAddMember}>
                <Text className="text-xs font-medium text-accent">+ Add</Text>
              </Pressable>
            ) : null}
          </View>

          {addingMember ? (
            <View className="mb-3 max-h-48 rounded-xl border border-border bg-surface">
              {candidates === null ? (
                <ActivityIndicator className="py-4" color={colors.accent} />
              ) : candidates.length === 0 ? (
                <Text className="p-3 text-sm text-text-tertiary">
                  No more Circle contacts to add.
                </Text>
              ) : (
                candidates.map((c) => (
                  <Pressable
                    key={c.contact_user_id}
                    testID={`group-info-add-${c.contact_user_id}`}
                    onPress={() => handleAddMember(c.contact_user_id)}
                    disabled={busyUserId === c.contact_user_id}
                    className="flex-row items-center gap-3 border-b border-border p-3 active:bg-surface-raised disabled:opacity-50"
                  >
                    <Avatar id={c.contact_user_id} name={c.contact_display_name} size={32} />
                    <Text className="flex-1 text-sm text-text-primary">{c.contact_display_name}</Text>
                    <Icon name="plus" size={16} color={colors.accent} />
                  </Pressable>
                ))
              )}
            </View>
          ) : null}

          {members.map((member) => {
            const isSelf = member.user_id === ownUserId;
            const isBusy = busyUserId === member.user_id;
            return (
              <View
                key={member.user_id}
                className="mb-2 flex-row items-center gap-3 rounded-xl border border-border bg-surface p-3"
              >
                <Avatar id={member.user_id} name={member.display_name} imageUrl={member.avatar_url} size={40} />
                <View className="flex-1">
                  <Text className="text-sm font-medium text-text-primary">
                    {member.display_name}
                    {isSelf ? " (you)" : ""}
                  </Text>
                  <Text className="text-xs text-text-tertiary">
                    {member.role === "admin" ? "Admin" : "Member"}
                  </Text>
                </View>
                {isBusy ? (
                  <ActivityIndicator color={colors.accent} />
                ) : (
                  <View className="flex-row gap-3">
                    {isAdmin ? (
                      <Pressable
                        testID={`group-info-role-${member.user_id}`}
                        onPress={() =>
                          handleSetRole(member.user_id, member.role === "admin" ? "member" : "admin")
                        }
                      >
                        <Text className="text-xs font-medium text-accent">
                          {member.role === "admin" ? "Demote" : "Promote"}
                        </Text>
                      </Pressable>
                    ) : null}
                    {isAdmin || isSelf ? (
                      <Pressable
                        testID={`group-info-remove-${member.user_id}`}
                        onPress={() => handleRemove(member.user_id)}
                      >
                        <Text className="text-xs font-medium text-danger">
                          {isSelf ? "Leave" : "Remove"}
                        </Text>
                      </Pressable>
                    ) : null}
                  </View>
                )}
              </View>
            );
          })}
        </View>
      )}
    </Screen>
  );
}
