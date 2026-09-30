import { useAudioPlayer, useAudioPlayerStatus } from "expo-audio";
import { File, Paths } from "expo-file-system";
import { useEffect, useState } from "react";
import { Pressable, Text, View } from "react-native";

import { decryptMediaBytes } from "../lib/crypto/chat-crypto";
import type { MediaKeyPayload } from "../lib/crypto/wire";
import { messagingApi } from "../lib/messaging-api";
import { getAccessToken } from "../lib/session";
import { Icon } from "./Icon";

interface VoiceNoteBubbleProps {
  messageId: string;
  mediaObjectId: string | null;
  // `undefined` while the message's own ciphertext is still decrypting,
  // `null` if that decryption failed or the message has no media key.
  keyPayload: MediaKeyPayload | null | undefined;
  isOwn: boolean;
  iconColor: string;
  textColor: string;
}

function formatDuration(ms: number): string {
  const totalSeconds = Math.round(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

// A fixed, non-analyzed bar pattern — a visual cue that this is a voice
// note, not a real waveform of the audio's actual amplitude (decrypting
// just to render a waveform would cost a full download+decrypt before
// the user ever presses play, for a detail most chat apps fake anyway).
const BAR_HEIGHTS = [6, 12, 8, 16, 10, 14, 7, 12, 9, 15, 6, 11, 8, 13, 7, 10];

/** Plays back a voice note: downloads the still-encrypted media object
 * (only on first play, then caches the decrypted file locally), decrypts
 * it with the key recovered from the message's own ciphertext, and hands
 * the result to expo-audio. */
export function VoiceNoteBubble({
  messageId,
  mediaObjectId,
  keyPayload,
  isOwn,
  iconColor,
  textColor,
}: VoiceNoteBubbleProps) {
  const [localUri, setLocalUri] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const player = useAudioPlayer(localUri ?? undefined);
  const status = useAudioPlayerStatus(player);

  useEffect(() => {
    if (localUri && status.isLoaded && !status.playing && status.currentTime === 0) {
      player.play();
    }
    // Only auto-play the moment a freshly-decrypted source becomes ready.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [localUri]);

  async function handlePress() {
    if (error || keyPayload === null || !mediaObjectId) return;
    if (localUri) {
      if (status.playing) {
        player.pause();
      } else {
        player.play();
      }
      return;
    }
    if (!keyPayload) return; // still resolving the key from the message
    setLoading(true);
    try {
      const token = await getAccessToken();
      if (!token) throw new Error("Not signed in.");
      const { download_url } = await messagingApi.getMediaDownloadUrl(token, mediaObjectId);
      const encrypted = await messagingApi.downloadEncryptedMedia(download_url);
      const audioBytes = decryptMediaBytes(encrypted, keyPayload);
      if (!audioBytes) throw new Error("Could not decrypt this voice note.");
      const file = new File(Paths.cache, `voice-${messageId}.m4a`);
      if (!file.exists) file.create();
      file.write(audioBytes);
      setLocalUri(file.uri);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }

  const durationMs = status.isLoaded && status.duration > 0 ? status.duration * 1000 : keyPayload?.durationMs;

  return (
    <Pressable
      testID={`voice-note-${messageId}`}
      onPress={handlePress}
      className="flex-row items-center gap-2 py-1"
      style={{ minWidth: 160 }}
    >
      <View
        className="h-9 w-9 items-center justify-center rounded-full"
        style={{ backgroundColor: isOwn ? "rgba(255,255,255,0.25)" : undefined }}
      >
        <Icon
          name={error ? "close" : status.playing ? "pause" : "play"}
          size={16}
          color={iconColor}
        />
      </View>
      <View className="flex-1 flex-row items-center gap-[2px]" style={{ height: 20 }}>
        {BAR_HEIGHTS.map((h, i) => (
          <View
            key={i}
            style={{ width: 2, height: h, borderRadius: 1, backgroundColor: iconColor, opacity: 0.7 }}
          />
        ))}
      </View>
      <Text style={{ color: textColor, fontSize: 11 }}>
        {error
          ? "Failed"
          : loading
            ? "…"
            : formatDuration(durationMs ?? 0)}
      </Text>
    </Pressable>
  );
}
