import { useEffect, useState } from "react";
import { Text, View } from "react-native";

import { Button } from "../../components/Button";
import { Screen } from "../../components/Screen";
import { useCall } from "../../lib/call-context";
import { circleApi } from "../../lib/circle-api";
import { getAccessToken } from "../../lib/session";

/**
 * §27: shown when a `call.ringing` WS event arrives, regardless of what
 * screen the user was on — see `lib/call-context.tsx`'s root-level
 * listener, which pushes this route.
 */
export default function IncomingCall() {
  const { incomingCall, answerIncomingCall, declineIncomingCall } = useCall();
  const [callerName, setCallerName] = useState<string | null>(null);

  useEffect(() => {
    if (!incomingCall) return;
    (async () => {
      const token = await getAccessToken();
      if (!token) return;
      // No generic "look up any user by id" endpoint exists (deliberate —
      // see ADR 0006), so this resolves the name from the caller's own
      // already-fetched Circle contact list instead of fabricating one.
      const contacts = await circleApi.listContacts(token).catch(() => []);
      const match = contacts.find((c) => c.contact_user_id === incomingCall.fromUserId);
      setCallerName(match?.contact_display_name ?? null);
    })();
  }, [incomingCall]);

  if (!incomingCall) {
    return (
      <Screen>
        <Text className="mt-8 text-base text-text-secondary">This call has ended.</Text>
      </Screen>
    );
  }

  return (
    <Screen scroll={false}>
      <View className="flex-1 items-center justify-center">
        <Text className="mb-2 text-3xl font-semibold text-text-primary">
          {incomingCall.callType === "video" ? "Incoming video call" : "Incoming call"}
        </Text>
        <Text className="mb-16 text-base text-text-secondary">
          from {callerName ?? "a Circle contact"}
        </Text>

        <View className="w-full flex-row gap-4">
          <View className="flex-1">
            <Button
              testID="decline-call-button"
              label="Decline"
              variant="secondary"
              onPress={declineIncomingCall}
            />
          </View>
          <View className="flex-1">
            <Button testID="answer-call-button" label="Answer" onPress={answerIncomingCall} />
          </View>
        </View>
      </View>
    </Screen>
  );
}
