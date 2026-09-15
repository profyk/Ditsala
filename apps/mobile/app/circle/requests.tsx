import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { FlatList, Text, View } from "react-native";

import { Button } from "../../components/Button";
import { Screen } from "../../components/Screen";
import { ApiError } from "../../lib/api";
import { circleApi, type ContactRequestListItem } from "../../lib/circle-api";
import { getAccessToken } from "../../lib/session";

export default function CircleRequests() {
  const router = useRouter();
  const [incoming, setIncoming] = useState<ContactRequestListItem[]>([]);
  const [outgoing, setOutgoing] = useState<ContactRequestListItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    const token = await getAccessToken();
    if (!token) {
      router.replace("/");
      return;
    }
    try {
      const [inc, out] = await Promise.all([
        circleApi.listIncomingRequests(token),
        circleApi.listOutgoingRequests(token),
      ]);
      setIncoming(inc);
      setOutgoing(out);
      setError(null);
    } catch {
      setError("Could not load your contact requests.");
    }
  }, [router]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  async function respond(requestId: string, action: "accept" | "decline") {
    const token = await getAccessToken();
    if (!token) return;
    setBusyId(requestId);
    try {
      if (action === "accept") {
        await circleApi.acceptContactRequest(token, requestId);
      } else {
        await circleApi.declineContactRequest(token, requestId);
      }
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update this request.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <Screen>
      <Text className="mb-2 mt-8 text-3xl font-semibold text-text-primary">Requests</Text>
      <Text className="mb-6 text-base text-text-secondary">
        People who want to connect, and requests you&apos;ve sent.
      </Text>

      {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}

      <Text className="mb-3 text-lg font-semibold text-text-primary">Incoming</Text>
      <FlatList
        data={incoming}
        keyExtractor={(item) => item.id}
        scrollEnabled={false}
        renderItem={({ item }) => (
          <View className="mb-3 rounded border border-border bg-surface p-4">
            <Text className="mb-3 text-base text-text-primary">
              {item.from_user_display_name}
            </Text>
            <View className="flex-row gap-3">
              <View className="flex-1">
                <Button
                  testID={`accept-button-${item.id}`}
                  label="Accept"
                  loading={busyId === item.id}
                  onPress={() => respond(item.id, "accept")}
                />
              </View>
              <View className="flex-1">
                <Button
                  testID={`decline-button-${item.id}`}
                  label="Decline"
                  variant="secondary"
                  loading={busyId === item.id}
                  onPress={() => respond(item.id, "decline")}
                />
              </View>
            </View>
          </View>
        )}
        ListEmptyComponent={
          <Text className="mb-6 text-sm text-text-tertiary">No incoming requests.</Text>
        }
      />

      <Text className="mb-3 mt-4 text-lg font-semibold text-text-primary">Sent</Text>
      <FlatList
        data={outgoing}
        keyExtractor={(item) => item.id}
        scrollEnabled={false}
        renderItem={({ item }) => (
          <View className="mb-3 rounded border border-border bg-surface p-4">
            <Text className="text-base text-text-primary">{item.to_user_display_name}</Text>
            <Text className="text-sm text-text-tertiary">Waiting for a response</Text>
          </View>
        )}
        ListEmptyComponent={
          <Text className="text-sm text-text-tertiary">No pending sent requests.</Text>
        }
      />
    </Screen>
  );
}
