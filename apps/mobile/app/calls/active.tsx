import { useEffect, useRef } from "react";
import { Platform, Text, View } from "react-native";

import { Button } from "../../components/Button";
import { useCall } from "../../lib/call-context";

const CONNECTION_LABEL: Record<string, string> = {
  connecting: "Connecting…",
  connected: "Connected",
  failed: "Connection lost",
  ended: "Call ended",
};

// `react-native-webrtc`'s `RTCView` is native-only — a static top-level
// import throws when bundled for web (see lib/call-session.ts's comment
// for why file-suffix swapping alone wasn't reliable here). Loaded lazily,
// only on native, same guard pattern as call-session.ts.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const RTCView: any = Platform.OS === "web" ? null : require("react-native-webrtc").RTCView;

/** call-context.tsx types `ActiveCall.localStream`/`remoteStream` as the
 * platform-agnostic global `MediaStream` (see its own comment) — on
 * native the runtime object is genuinely react-native-webrtc's own
 * MediaStream, which adds `.toURL()` for RTCView. This is just that one
 * extra method, named locally instead of importing the library's type
 * (even type-only) to keep this file's only react-native-webrtc
 * reference the lazy `require()` above. */
interface NativeMediaStream {
  toURL(): string;
}

/** Web-only: a real browser `MediaStream` isn't renderable via a JSX prop
 * (`srcObject` must be set imperatively) — this is the web equivalent of
 * `RTCView`. `stream` is cast from `activeCall`'s platform-agnostic
 * MediaStream type (see call-context.tsx) since on web it's genuinely a
 * browser MediaStream (lib/call-session.ts's web branch). */
function WebVideoStream({ stream, mirror }: { stream: MediaStream; mirror?: boolean }) {
  const ref = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    if (ref.current) ref.current.srcObject = stream;
  }, [stream]);

  return (
    <video
      ref={ref}
      autoPlay
      playsInline
      muted={mirror}
      style={{
        width: "100%",
        height: "100%",
        objectFit: "cover",
        transform: mirror ? "scaleX(-1)" : undefined,
      }}
    />
  );
}

/**
 * §27: the in-call screen — real local/remote video (native `RTCView`,
 * or a plain `<video>` on web) when the call is (or switches to) video,
 * audio-only otherwise. Mute, end, and the voice<->video switch
 * ("clients can switch anytime") are all wired to real
 * `CallSession`/`callsApi` calls via `useCall()`.
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
        Platform.OS === "web" ? (
          <View style={{ flex: 1 }}>
            <WebVideoStream stream={activeCall.remoteStream as unknown as MediaStream} />
          </View>
        ) : (
          <RTCView
            streamURL={(activeCall.remoteStream as unknown as NativeMediaStream).toURL()}
            style={{ flex: 1 }}
            objectFit="cover"
          />
        )
      ) : (
        <View className="flex-1 items-center justify-center">
          <Text className="text-2xl font-semibold text-text-primary">
            {CONNECTION_LABEL[activeCall.connectionState]}
          </Text>
        </View>
      )}

      {isVideo && activeCall.localStream ? (
        <View className="absolute right-4 top-16 h-40 w-28 overflow-hidden rounded border border-border">
          {Platform.OS === "web" ? (
            <WebVideoStream stream={activeCall.localStream as unknown as MediaStream} mirror />
          ) : (
            <RTCView
              streamURL={(activeCall.localStream as unknown as NativeMediaStream).toURL()}
              style={{ flex: 1 }}
              objectFit="cover"
              mirror
            />
          )}
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
