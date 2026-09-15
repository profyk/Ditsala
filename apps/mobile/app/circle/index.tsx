import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { FlatList, Text, View } from "react-native";

import { Button } from "../../components/Button";
import { Screen } from "../../components/Screen";
import { ApiError } from "../../lib/api";
import { useCall } from "../../lib/call-context";
import { circleApi, type Contact } from "../../lib/circle-api";
import { messagingApi } from "../../lib/messaging-api";
import { getAccessToken } from "../../lib/session";

const TIER_LABEL: Record<Contact["tier"], string> = {
  unverified: "Request pending",
  verified: "Connected",
  trusted: "In your Circle",
  blocked: "Blocked",
};

/**
 * §22-23: every contact the user has, from a pending request through to a
 * safety-number-verified Circle member. "Verify" doesn't display a
 * fabricated safety number — that needs real Signal identity keys, which
 * don't exist without the native libsignal module (ADR 0005). It records
 * a genuine, real attestation instead: the user confirms the match through
 * some other real channel (in person, today), and the backend state change
 * (unverified/verified → trusted) is completely real.
 */
export default function Circle() {
  const router = useRouter();
  const { startCall } = useCall();
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [incomingCount, setIncomingCount] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [verifyingId, setVerifyingId] = useState<string | null>(null);
  const [callingId, setCallingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    const token = await getAccessToken();
    if (!token) {
      router.replace("/");
      return;
    }
    try {
      const [contactList, incoming] = await Promise.all([
        circleApi.listContacts(token),
        circleApi.listIncomingRequests(token),
      ]);
      setContacts(contactList);
      setIncomingCount(incoming.length);
      setError(null);
    } catch {
      setError("Could not load your Circle.");
    }
  }, [router]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  async function handleVerify(contactUserId: string) {
    const token = await getAccessToken();
    if (!token) return;
    setVerifyingId(contactUserId);
    try {
      await circleApi.verifySafetyNumber(token, contactUserId);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not verify this contact.");
    } finally {
      setVerifyingId(null);
    }
  }

  async function handleCall(contactUserId: string, callType: "voice" | "video") {
    const token = await getAccessToken();
    if (!token) return;
    setCallingId(contactUserId);
    try {
      // §27 calls are 1:1 over a `direct` conversation — this reuses the
      // real §18-21 conversation the two are already messaging-eligible
      // through (idempotent: returns the existing one if there is one).
      const conversation = await messagingApi.startDirectConversation(token, contactUserId);
      await startCall(conversation.id, callType);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start the call.");
    } finally {
      setCallingId(null);
    }
  }

  return (
    <Screen>
      <Text className="mb-2 mt-8 text-3xl font-semibold text-text-primary">Circle</Text>
      <Text className="mb-6 text-base text-text-secondary">
        The people you can share location and SOS alerts with.
      </Text>

      {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}

      <Button
        testID="circle-requests-button"
        label={incomingCount > 0 ? `Requests (${incomingCount})` : "Requests"}
        onPress={() => router.push("/circle/requests")}
        variant="secondary"
      />
      <View className="h-3" />
      <Button
        testID="circle-location-button"
        label="Location"
        onPress={() => router.push("/location")}
        variant="secondary"
      />
      <View className="h-3" />
      <Button
        testID="circle-add-button"
        label="Add to Circle"
        onPress={() => router.push("/circle/add")}
      />

      <FlatList
        className="mt-6"
        data={contacts}
        keyExtractor={(item) => item.id}
        renderItem={({ item }) => (
          <View className="mb-3 rounded border border-border bg-surface p-4">
            <Text className="text-base text-text-primary">{item.contact_display_name}</Text>
            <Text className="mb-3 text-sm text-text-tertiary">{TIER_LABEL[item.tier]}</Text>
            {item.tier === "verified" ? (
              <Button
                testID={`verify-button-${item.contact_user_id}`}
                label="Verify in person"
                variant="secondary"
                loading={verifyingId === item.contact_user_id}
                onPress={() => handleVerify(item.contact_user_id)}
              />
            ) : null}
            {item.tier === "trusted" ? (
              <View className="flex-row gap-3">
                <View className="flex-1">
                  <Button
                    testID={`voice-call-button-${item.contact_user_id}`}
                    label="Voice call"
                    variant="secondary"
                    loading={callingId === item.contact_user_id}
                    onPress={() => handleCall(item.contact_user_id, "voice")}
                  />
                </View>
                <View className="flex-1">
                  <Button
                    testID={`video-call-button-${item.contact_user_id}`}
                    label="Video call"
                    variant="secondary"
                    loading={callingId === item.contact_user_id}
                    onPress={() => handleCall(item.contact_user_id, "video")}
                  />
                </View>
              </View>
            ) : null}
          </View>
        )}
        ListEmptyComponent={
          <Text className="text-sm text-text-tertiary">
            No contacts yet — tap &quot;Add to Circle&quot; to send your first request.
          </Text>
        }
      />
    </Screen>
  );
}
