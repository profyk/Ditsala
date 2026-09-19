import { dark } from "@ditsala/ui-tokens";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { Pressable, Text, View } from "react-native";

import { Avatar } from "../components/Avatar";
import { Icon, type IconName } from "../components/Icon";
import { TabScreen } from "../components/TabScreen";
import { authApi, type CurrentUser } from "../lib/api";
import { registerWithBackend } from "../lib/crypto/keystore";
import { messagingSocket } from "../lib/messaging-ws";
import { getAccessToken } from "../lib/session";

interface QuickActionProps {
  testID: string;
  label: string;
  sub: string;
  icon: IconName;
  onPress: () => void;
}

function QuickAction({ testID, label, sub, icon, onPress }: QuickActionProps) {
  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      className="flex-1 rounded-xl border border-border bg-surface p-4 active:bg-surface-raised"
    >
      <View
        className="mb-3 h-10 w-10 items-center justify-center rounded-full"
        style={{ backgroundColor: dark.accentMuted }}
      >
        <Icon name={icon} size={20} color={dark.accent} />
      </View>
      <Text className="text-base font-semibold text-text-primary">{label}</Text>
      <Text className="text-xs text-text-tertiary">{sub}</Text>
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
  // SOS is a VIP-tier feature (backend/app/api/v1/routers/sos.py enforces
  // this too) — default to hidden until the tier is known, same "don't
  // flash it" pattern settings/index.tsx already uses for the tier-gated
  // "Log out" row.
  const isVip = me?.account_tier === "vip";

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
    <TabScreen>
      <View className="mb-6 mt-4 flex-row items-center gap-3">
        <Pressable testID="home-avatar" onPress={() => router.push("/account/profile")}>
          <Avatar
            id={me?.id ?? "me"}
            name={me?.display_name ?? "?"}
            imageUrl={me?.avatar_url}
            size={52}
            ring
          />
        </Pressable>
        <View className="flex-1">
          <Text className="text-xs font-medium uppercase tracking-widest text-text-tertiary">
            Welcome back
          </Text>
          <Text className="text-xl font-bold text-text-primary">
            {me ? me.display_name.split(" ")[0] : "…"}
          </Text>
        </View>
      </View>

      {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}

      {isVip ? (
        <Pressable
          testID="sos-nav-button"
          onPress={() => router.push("/sos")}
          className="mb-6 flex-row items-center gap-4 rounded-2xl bg-danger p-5 active:opacity-90"
          style={{
            shadowColor: dark.danger,
            shadowOpacity: 0.4,
            shadowRadius: 16,
            shadowOffset: { width: 0, height: 8 },
            elevation: 6,
          }}
        >
          <View className="h-12 w-12 items-center justify-center rounded-full bg-white/20">
            <Icon name="shield" size={24} color="#FFFFFF" />
          </View>
          <View className="flex-1">
            <Text className="text-lg font-bold text-white">Emergency SOS</Text>
            <Text className="text-sm text-white/85">Alert your trusted Circle instantly</Text>
          </View>
          <Icon name="chevron-right" size={20} color="#FFFFFF" />
        </Pressable>
      ) : null}

      <Text className="mb-3 text-xs font-medium uppercase tracking-widest text-text-tertiary">
        Quick actions
      </Text>
      <View className="mb-8 flex-row gap-3">
        <QuickAction
          testID="circle-nav-button"
          label="Circle"
          sub="Your trusted contacts"
          icon="circle"
          onPress={() => router.push("/circle")}
        />
        <QuickAction
          testID="messages-nav-button"
          label="Messages"
          sub="End-to-end encrypted"
          icon="messages"
          onPress={() => router.push("/messages")}
        />
      </View>
      <View className="mb-8 flex-row gap-3">
        <QuickAction
          testID="location-nav-button"
          label="Location"
          sub="Share where you are"
          icon="location"
          onPress={() => router.push("/location")}
        />
      </View>
    </TabScreen>
  );
}
