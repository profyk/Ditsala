import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, FlatList, Pressable, Text, TextInput, View } from "react-native";

import { Avatar } from "../../components/Avatar";
import { Button } from "../../components/Button";
import { Icon } from "../../components/Icon";
import { Screen } from "../../components/Screen";
import { ApiError } from "../../lib/api";
import { circleApi, type Contact } from "../../lib/circle-api";
import { messagingApi } from "../../lib/messaging-api";
import { getAccessToken } from "../../lib/session";
import { useTheme } from "../../lib/theme-context";

/**
 * "New group" — createGroupConversation has had zero UI callers since
 * the day it shipped (a real, previously-disclosed gap: "the backend's
 * Circle-tier gate exists; no mobile screen calls it yet"). Only
 * verified/trusted contacts are selectable — matches the backend's own
 * gate (every member must already be an accepted Circle contact), so
 * this never offers a choice that would just come back as a 400.
 */
export default function NewGroup() {
  const router = useRouter();
  const { colors } = useTheme();
  const [contacts, setContacts] = useState<Contact[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    const token = await getAccessToken();
    if (!token) {
      router.replace("/");
      return;
    }
    try {
      const all = await circleApi.listContacts(token);
      setContacts(all.filter((c) => c.tier === "verified" || c.tier === "trusted"));
    } catch {
      setError("Could not load your Circle.");
    }
  }, [router]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  function toggle(userId: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(userId)) next.delete(userId);
      else next.add(userId);
      return next;
    });
  }

  async function handleCreate() {
    if (selected.size === 0) return;
    const token = await getAccessToken();
    if (!token) {
      router.replace("/");
      return;
    }
    setCreating(true);
    setError(null);
    try {
      const conversation = await messagingApi.createGroupConversation(
        token,
        [...selected],
        title.trim() || undefined
      );
      router.replace(`/messages/${conversation.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create this group.");
    } finally {
      setCreating(false);
    }
  }

  return (
    <Screen scroll={false}>
      <View className="mb-4 mt-8 flex-row items-center gap-3">
        <Pressable
          testID="new-group-back-button"
          onPress={() => router.back()}
          className="h-9 w-9 items-center justify-center rounded-full active:bg-surface-raised"
        >
          <Icon name="chevron-left" size={20} color={colors.textPrimary} />
        </Pressable>
        <Text className="text-lg font-bold text-text-primary">New group</Text>
      </View>

      <TextInput
        testID="new-group-title-input"
        value={title}
        onChangeText={setTitle}
        placeholder="Group name (optional)"
        placeholderTextColor={colors.textTertiary}
        className="mb-4 rounded-xl border border-border bg-surface px-4 py-3 text-text-primary"
      />

      {error ? <Text className="mb-3 text-sm text-danger">{error}</Text> : null}

      <Text className="mb-2 text-xs font-medium uppercase tracking-widest text-text-tertiary">
        Select from your Circle ({selected.size} selected)
      </Text>

      {contacts === null ? (
        <ActivityIndicator color={colors.accent} />
      ) : contacts.length === 0 ? (
        <View className="items-center rounded-xl border border-dashed border-border py-10">
          <Text className="px-8 text-center text-sm text-text-tertiary">
            You need at least one verified Circle contact before you can start a group.
          </Text>
        </View>
      ) : (
        <FlatList
          className="flex-1"
          data={contacts}
          keyExtractor={(item) => item.id}
          renderItem={({ item }) => {
            const isSelected = selected.has(item.contact_user_id);
            return (
              <Pressable
                testID={`new-group-contact-${item.contact_user_id}`}
                onPress={() => toggle(item.contact_user_id)}
                className="mb-2 flex-row items-center gap-3 rounded-xl border border-border bg-surface p-3 active:bg-surface-raised"
              >
                <Avatar id={item.contact_user_id} name={item.contact_display_name} size={40} />
                <Text className="flex-1 text-base text-text-primary" numberOfLines={1}>
                  {item.contact_display_name}
                </Text>
                <View
                  className="h-6 w-6 items-center justify-center rounded-full border-2"
                  style={{
                    borderColor: isSelected ? colors.accent : colors.border,
                    backgroundColor: isSelected ? colors.accent : "transparent",
                  }}
                >
                  {isSelected ? <Icon name="check" size={12} color="#FFFFFF" /> : null}
                </View>
              </Pressable>
            );
          }}
        />
      )}

      <View className="pb-4 pt-3">
        <Button
          testID="new-group-create-button"
          label={creating ? "Creating…" : "Create group"}
          onPress={handleCreate}
          disabled={selected.size === 0 || creating}
          loading={creating}
        />
      </View>
    </Screen>
  );
}
