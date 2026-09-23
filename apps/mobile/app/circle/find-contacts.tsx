import * as Contacts from "expo-contacts";
import { useRouter } from "expo-router";
import { useState } from "react";
import { FlatList, Text, View } from "react-native";

import { Avatar } from "../../components/Avatar";
import { Button } from "../../components/Button";
import { Icon } from "../../components/Icon";
import { Screen } from "../../components/Screen";
import { ApiError } from "../../lib/api";
import { circleApi, type MatchedContact } from "../../lib/circle-api";
import { getAccessToken } from "../../lib/session";
import { useTheme } from "../../lib/theme-context";

type RequestState = "idle" | "sending" | "sent" | "error";

/**
 * §22 `phone_match` — reads the device's contacts (phone numbers only,
 * never uploaded/stored — matched server-side by exact phone lookup and
 * discarded after the response, see CircleService.match_contacts) and
 * shows which ones already have a DITSALA account. Matching someone
 * here only sends a contact request (same as QR/link) — messaging still
 * requires them to accept, per §22's trust model.
 */
export default function FindContacts() {
  const router = useRouter();
  const { colors } = useTheme();
  const [status, setStatus] = useState<"idle" | "loading" | "done">("idle");
  const [matches, setMatches] = useState<MatchedContact[]>([]);
  const [requestState, setRequestState] = useState<Record<string, RequestState>>({});
  const [error, setError] = useState<string | null>(null);

  async function handleFindContacts() {
    setError(null);
    setStatus("loading");
    try {
      const { status: permission } = await Contacts.requestPermissionsAsync();
      if (permission !== "granted") {
        setError("Contacts access is needed to find people you know on DITSALA.");
        setStatus("idle");
        return;
      }

      const token = await getAccessToken();
      if (!token) {
        router.replace("/");
        return;
      }

      const { data } = await Contacts.getContactsAsync({
        fields: [Contacts.Fields.PhoneNumbers],
      });
      const phones = new Set<string>();
      for (const contact of data) {
        for (const phone of contact.phoneNumbers ?? []) {
          const normalized = phone.number?.replace(/[^\d+]/g, "");
          if (normalized) phones.add(normalized);
        }
      }

      const found = await circleApi.matchContacts(token, Array.from(phones));
      setMatches(found);
      setStatus("done");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not check your contacts.");
      setStatus("idle");
    }
  }

  async function handleAdd(userId: string) {
    const token = await getAccessToken();
    if (!token) return;
    setRequestState((s) => ({ ...s, [userId]: "sending" }));
    try {
      await circleApi.sendContactRequest(token, userId, "phone_match");
      setRequestState((s) => ({ ...s, [userId]: "sent" }));
    } catch {
      setRequestState((s) => ({ ...s, [userId]: "error" }));
    }
  }

  if (status !== "done") {
    return (
      <Screen scroll={false}>
        <View className="flex-1 items-center justify-center">
          <View
            className="mb-6 h-20 w-20 items-center justify-center rounded-full"
            style={{ backgroundColor: colors.accentMuted }}
          >
            <Icon name="circle" size={32} color={colors.accent} />
          </View>
          <Text className="mb-2 text-2xl font-extrabold text-text-primary">
            Find people you know
          </Text>
          <Text className="mb-10 max-w-xs text-center text-base text-text-secondary">
            We&apos;ll check which of your phone contacts already have a DITSALA account. Your
            contact list is never uploaded or stored — only phone numbers are checked.
          </Text>

          {error ? <Text className="mb-4 text-center text-sm text-danger">{error}</Text> : null}

          <View className="w-full">
            <Button
              testID="find-contacts-button"
              label="Check my contacts"
              icon="search"
              onPress={handleFindContacts}
              loading={status === "loading"}
            />
          </View>
        </View>
      </Screen>
    );
  }

  return (
    <Screen>
      <Text className="mb-2 mt-4 text-2xl font-bold text-text-primary">On DITSALA</Text>
      <Text className="mb-6 text-sm text-text-secondary">
        {matches.length > 0
          ? `${matches.length} of your contacts ${matches.length === 1 ? "is" : "are"} already here.`
          : "None of your contacts are on DITSALA yet."}
      </Text>

      <FlatList
        scrollEnabled={false}
        data={matches}
        keyExtractor={(item) => item.user_id}
        renderItem={({ item }) => {
          const state = requestState[item.user_id] ?? "idle";
          return (
            <View className="mb-2 flex-row items-center gap-3 rounded-xl border border-border bg-surface p-3">
              <Avatar id={item.user_id} name={item.display_name} imageUrl={item.avatar_url} />
              <Text className="flex-1 text-base font-medium text-text-primary" numberOfLines={1}>
                {item.display_name}
              </Text>
              <Button
                testID={`add-contact-${item.user_id}`}
                label={state === "sent" ? "Sent" : state === "error" ? "Retry" : "Add"}
                size="md"
                variant={state === "sent" ? "secondary" : "primary"}
                disabled={state === "sent"}
                loading={state === "sending"}
                onPress={() => handleAdd(item.user_id)}
              />
            </View>
          );
        }}
        ListEmptyComponent={
          <View className="items-center rounded-xl border border-dashed border-border py-12">
            <View
              className="mb-3 h-14 w-14 items-center justify-center rounded-full"
              style={{ backgroundColor: colors.accentMuted }}
            >
              <Icon name="circle" size={26} color={colors.accent} />
            </View>
            <Text className="mb-1 text-base font-semibold text-text-primary">No matches yet</Text>
            <Text className="px-8 text-center text-sm text-text-tertiary">
              Invite someone instead, or check back once more of your contacts join.
            </Text>
          </View>
        }
      />

      <View className="mt-6">
        <Button label="Done" variant="secondary" onPress={() => router.replace("/circle")} />
      </View>
    </Screen>
  );
}
