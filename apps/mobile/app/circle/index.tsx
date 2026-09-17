import { dark } from "@ditsala/ui-tokens";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { FlatList, Pressable, Text, View } from "react-native";

import { Avatar } from "../../components/Avatar";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Icon } from "../../components/Icon";
import { TabScreen } from "../../components/TabScreen";
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

const TIER_TONE: Record<Contact["tier"], "neutral" | "info" | "accent" | "danger"> = {
  unverified: "neutral",
  verified: "info",
  trusted: "accent",
  blocked: "danger",
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
  const [messagingId, setMessagingId] = useState<string | null>(null);

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

  async function handleMessage(contactUserId: string) {
    const token = await getAccessToken();
    if (!token) return;
    setMessagingId(contactUserId);
    try {
      const conversation = await messagingApi.startDirectConversation(token, contactUserId);
      router.push(`/messages/${conversation.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start this conversation.");
    } finally {
      setMessagingId(null);
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
    <TabScreen>
      <View className="mb-1 mt-4 flex-row items-center justify-between">
        <Text className="text-2xl font-bold text-text-primary">Circle</Text>
        <Pressable
          testID="circle-add-button"
          onPress={() => router.push("/circle/add")}
          className="h-10 w-10 items-center justify-center rounded-full bg-accent"
        >
          <Icon name="plus" size={18} color="#FFFFFF" />
        </Pressable>
      </View>
      <Text className="mb-5 text-sm text-text-secondary">
        The people you can share location and SOS alerts with.
      </Text>

      {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}

      <View className="mb-5 flex-row gap-3">
        <Pressable
          testID="circle-requests-button"
          onPress={() => router.push("/circle/requests")}
          className="flex-1 flex-row items-center justify-between rounded-xl border border-border bg-surface p-3.5"
        >
          <Text className="text-sm font-medium text-text-primary">
            {incomingCount > 0 ? `Requests (${incomingCount})` : "Requests"}
          </Text>
          <Icon name="chevron-right" size={16} color={dark.textTertiary} />
        </Pressable>
        <Pressable
          testID="circle-location-button"
          onPress={() => router.push("/location")}
          className="flex-1 flex-row items-center justify-between rounded-xl border border-border bg-surface p-3.5"
        >
          <Text className="text-sm font-medium text-text-primary">Location</Text>
          <Icon name="chevron-right" size={16} color={dark.textTertiary} />
        </Pressable>
      </View>

      <FlatList
        scrollEnabled={false}
        data={contacts}
        keyExtractor={(item) => item.id}
        renderItem={({ item }) => (
          <View className="mb-3 rounded-xl border border-border bg-surface p-4">
            <View className="mb-3 flex-row items-center gap-3">
              <Avatar id={item.contact_user_id} name={item.contact_display_name} />
              <View className="flex-1">
                <Text className="text-base font-semibold text-text-primary">
                  {item.contact_display_name}
                </Text>
                <View className="mt-1 flex-row">
                  <Badge label={TIER_LABEL[item.tier]} tone={TIER_TONE[item.tier]} />
                </View>
              </View>
            </View>
            {item.tier === "verified" || item.tier === "trusted" ? (
              <View className="mb-2">
                <Button
                  testID={`message-button-${item.contact_user_id}`}
                  label="Message"
                  icon="messages"
                  loading={messagingId === item.contact_user_id}
                  onPress={() => handleMessage(item.contact_user_id)}
                />
              </View>
            ) : null}
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
                    label="Voice"
                    icon="phone"
                    variant="secondary"
                    loading={callingId === item.contact_user_id}
                    onPress={() => handleCall(item.contact_user_id, "voice")}
                  />
                </View>
                <View className="flex-1">
                  <Button
                    testID={`video-call-button-${item.contact_user_id}`}
                    label="Video"
                    icon="video"
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
          <View className="items-center rounded-xl border border-dashed border-border py-12">
            <View
              className="mb-3 h-14 w-14 items-center justify-center rounded-full"
              style={{ backgroundColor: dark.accentMuted }}
            >
              <Icon name="circle" size={26} color={dark.accent} />
            </View>
            <Text className="mb-1 text-base font-semibold text-text-primary">No contacts yet</Text>
            <Text className="px-8 text-center text-sm text-text-tertiary">
              Tap the + button to send your first request.
            </Text>
          </View>
        }
      />
    </TabScreen>
  );
}
