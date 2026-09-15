import { Text, View } from "react-native";
import { RTCView } from "react-native-webrtc";

import { Button } from "../../components/Button";
import { useCall } from "../../lib/call-context";

const CONNECTION_LABEL: Record<string, string> = {
  connecting: "Connecting…",
  connected: "Connected",
  failed: "Connection lost",
  ended: "Call ended",
};

/**
 * §27: the in-call screen — real local/remote video via `RTCView` when
 * the call is (or switches to) video, audio-only otherwise. Mute, end,
 * and the voice<->video switch ("clients can switch anytime") are all
 * wired to real `CallSession`/`callsApi` calls via `useCall()`.
 */
export default function ActiveCall() {
  const { activeCall, toggleMute, switchMedia, endActiveCall } = useCall();

  if (!activeCall) {
    return (
      <View className="flex-1 items-center justify-center bg-background">
        <Text className="text-base text-text-secondary">This call has ended.</Text>
      </View>
    );
  }

  const isVideo = activeCall.callType === "video";

  return (
    <View className="flex-1 bg-background">
      {isVideo && activeCall.remoteStream ? (
        <RTCView
          streamURL={activeCall.remoteStream.toURL()}
          style={{ flex: 1 }}
          objectFit="cover"
        />
      ) : (
        <View className="flex-1 items-center justify-center">
          <Text className="text-2xl font-semibold text-text-primary">
            {CONNECTION_LABEL[activeCall.connectionState]}
          </Text>
        </View>
      )}

      {isVideo && activeCall.localStream ? (
        <View className="absolute right-4 top-16 h-40 w-28 overflow-hidden rounded border border-border">
          <RTCView
            streamURL={activeCall.localStream.toURL()}
            style={{ flex: 1 }}
            objectFit="cover"
            mirror
          />
        </View>
      ) : null}

      {!isVideo ? (
        <View className="absolute left-6 right-6 top-16">
          <Text className="text-center text-sm text-text-tertiary">
            {CONNECTION_LABEL[activeCall.connectionState]}
          </Text>
        </View>
      ) : null}

      <View className="absolute bottom-12 left-6 right-6 flex-row justify-center gap-4">
        <View className="flex-1">
          <Button
            testID="mute-button"
            label={activeCall.muted ? "Unmute" : "Mute"}
            variant="secondary"
            onPress={toggleMute}
          />
        </View>
        <View className="flex-1">
          <Button
            testID="switch-media-button"
            label={isVideo ? "Turn camera off" : "Turn camera on"}
            variant="secondary"
            onPress={() => switchMedia(isVideo ? "voice" : "video")}
          />
        </View>
        <View className="flex-1">
          <Button testID="end-call-button" label="End call" onPress={endActiveCall} />
        </View>
      </View>
    </View>
  );
}
