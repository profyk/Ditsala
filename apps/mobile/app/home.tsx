import { useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { Image, Pressable, Text, View } from "react-native";

import { Screen } from "../components/Screen";
import { authApi, type CurrentUser } from "../lib/api";
import { registerWithBackend } from "../lib/crypto/keystore";
import { messagingSocket } from "../lib/messaging-ws";
import { getAccessToken } from "../lib/session";

interface NavTileProps {
  testID: string;
  label: string;
  emoji: string;
  onPress: () => void;
  danger?: boolean;
}

function NavTile({ testID, label, emoji, onPress, danger }: NavTileProps) {
  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      className={`flex-1 items-center rounded-lg border py-5 active:bg-surface-raised ${
        danger ? "border-danger/40" : "border-border"
      } bg-surface`}
    >
      <Text className="mb-1 text-2xl">{emoji}</Text>
      <Text className={`text-sm font-semibold ${danger ? "text-danger" : "text-text-primary"}`}>
        {label}
      </Text>
    </Pressable>
  );
}

/**
 * Authenticated home — the app's real dashboard. Also the single choke
 * point every authenticated flow (login, unlock, onboarding completion)
 * routes through, so it's where the realtime socket connects — calls
 * and messaging both need it live from here on.
 */
export default function Home() {
  const router = useRouter();
  const [me, setMe] = useState<CurrentUser | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const accessToken = await getAccessToken();
    if (!accessToken) {
      router.replace("/");
      return;
    }
    try {
      setMe(await authApi.getMe(accessToken));
      messagingSocket.connect(accessToken);
    } catch {
      setError("Could not load your account.");
      return;
    }
    // Best-effort: a transient failure here shouldn't block the
    // dashboard from loading — messaging screens surface their own
    // error if keys genuinely never got registered.
    registerWithBackend(accessToken).catch(() => undefined);
  }, [router]);

  useEffect(() => {
    load();
    return () => messagingSocket.disconnect();
  }, [load]);

  return (
    <Screen>
      <View className="mb-8 mt-8 flex-row items-center gap-3">
        <Pressable
          testID="home-avatar"
          onPress={() => router.push("/account/profile")}
          className="h-14 w-14 items-center justify-center overflow-hidden rounded-full border border-border bg-surface"
        >
          {me?.avatar_url ? (
            <Image source={{ uri: me.avatar_url }} className="h-14 w-14" />
          ) : (
            <Text className="text-xl font-semibold text-text-tertiary">
              {(me?.display_name ?? "?").charAt(0).toUpperCase()}
            </Text>
          )}
        </Pressable>
        <View className="flex-1">
          <Text className="text-2xl font-semibold text-text-primary">
            {me ? `Welcome back, ${me.display_name.split(" ")[0]}` : "Welcome back"}
          </Text>
          <Text className="text-base text-text-secondary">Your trusted circle, in one place.</Text>
        </View>
      </View>

      {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}

      <View className="mb-3 flex-row gap-3">
        <NavTile testID="sos-nav-button" label="SOS" emoji="🆘" danger onPress={() => router.push("/sos")} />
        <NavTile testID="circle-nav-button" label="Circle" emoji="🤝" onPress={() => router.push("/circle")} />
      </View>
      <View className="mb-8 flex-row gap-3">
        <NavTile
          testID="messages-nav-button"
          label="Messages"
          emoji="💬"
          onPress={() => router.push("/messages")}
        />
        <NavTile
          testID="meet-nav-button"
          label="Meet"
          emoji="🎥"
          onPress={() => router.push("/meet/schedule")}
        />
      </View>

      <Pressable
        testID="settings-nav-button"
        onPress={() => router.push("/settings")}
        className="flex-row items-center justify-between rounded-lg border border-border bg-surface p-4 active:bg-surface-raised"
      >
        <Text className="text-base text-text-primary">Settings</Text>
        <Text className="text-text-tertiary">›</Text>
      </Pressable>
    </Screen>
  );
}
