import { File, Paths } from "expo-file-system";
import { useVideoPlayer, VideoView } from "expo-video";
import { useEffect, useState } from "react";
import { ActivityIndicator, Image, View } from "react-native";

import { decryptMediaBytes } from "../lib/crypto/chat-crypto";
import type { MediaKeyPayload } from "../lib/crypto/wire";
import { messagingApi } from "../lib/messaging-api";
import { getAccessToken } from "../lib/session";
import { Icon } from "./Icon";

interface MediaBubbleProps {
  messageId: string;
  mediaObjectId: string | null;
  // `undefined` while the message's own ciphertext is still decrypting,
  // `null` if that decryption failed or the message has no media key.
  keyPayload: MediaKeyPayload | null | undefined;
  iconColor: string;
}

function extensionFor(mimeType: string): string {
  if (mimeType.startsWith("video/")) return mimeType.includes("mp4") ? "mp4" : "mov";
  if (mimeType.includes("png")) return "png";
  return "jpg";
}

/** Downloads and decrypts a media (image/video) message automatically
 * on mount — unlike voice notes, which stay lazy until tapped, a chat
 * bubble showing an image is expected to preview it without a tap. The
 * FlatList this renders inside already virtualizes off-screen rows, so
 * this only actually runs for messages currently on screen. */
export function MediaBubble({ messageId, mediaObjectId, keyPayload, iconColor }: MediaBubbleProps) {
  const [localUri, setLocalUri] = useState<string | null>(null);
  const [isVideo, setIsVideo] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function run() {
      if (!mediaObjectId || !keyPayload) return;
      try {
        const token = await getAccessToken();
        if (!token) throw new Error("Not signed in.");
        const { download_url } = await messagingApi.getMediaDownloadUrl(token, mediaObjectId);
        const encrypted = await messagingApi.downloadEncryptedMedia(download_url);
        const bytes = decryptMediaBytes(encrypted, keyPayload);
        if (!bytes) throw new Error("Could not decrypt this attachment.");
        const ext = extensionFor(keyPayload.mimeType);
        const file = new File(Paths.cache, `media-${messageId}.${ext}`);
        if (!file.exists) file.create();
        file.write(bytes);
        if (!cancelled) {
          setIsVideo(keyPayload.mimeType.startsWith("video/"));
          setLocalUri(file.uri);
        }
      } catch {
        if (!cancelled) setError(true);
      }
    }
    run();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mediaObjectId, keyPayload]);

  const player = useVideoPlayer(isVideo ? localUri : null);

  if (error) {
    return (
      <View className="h-40 w-40 items-center justify-center rounded-lg bg-surface-raised">
        <Icon name="close" size={20} color={iconColor} />
      </View>
    );
  }

  if (!localUri) {
    return (
      <View className="h-40 w-40 items-center justify-center rounded-lg bg-surface-raised">
        <ActivityIndicator color={iconColor} />
      </View>
    );
  }

  if (isVideo) {
    return (
      <VideoView
        style={{ height: 220, width: 220, borderRadius: 12 }}
        player={player}
        nativeControls
        contentFit="cover"
      />
    );
  }

  return (
    <Image
      source={{ uri: localUri }}
      style={{ height: 220, width: 220, borderRadius: 12 }}
      resizeMode="cover"
    />
  );
}
