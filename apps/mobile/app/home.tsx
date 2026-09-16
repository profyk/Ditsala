import { useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { FlatList, Text, View } from "react-native";

import { Button } from "../components/Button";
import { Screen } from "../components/Screen";
import { authApi, type Device } from "../lib/api";
import { messagingSocket } from "../lib/messaging-ws";
import { clearSession, getAccessToken, getRefreshToken } from "../lib/session";

/**
 * Placeholder authenticated home — Phase 4+ builds the real app (Circle,
 * conversations, etc.). This exists to prove the session/device-registry
 * plumbing works end to end: it lists the signed-in devices and can log
 * out (this device) or everywhere. Also the single choke point every
 * authenticated flow (login, unlock, onboarding completion) routes
 * through, so it's where the realtime socket connects — call signaling
 * and (once built) messaging both need it live from here on.
 */
export default function Home() {
  const router = useRouter();
  const [devices, setDevices] = useState<Device[]>([]);
  const [error, setError] = useState<string | null>(null);

  const loadDevices = useCallback(async () => {
    const accessToken = await getAccessToken();
    if (!accessToken) {
      router.replace("/");
      return;
    }
    try {
      setDevices(await authApi.listDevices(accessToken));
      messagingSocket.connect(accessToken);
    } catch {
      setError("Could not load your devices.");
    }
  }, [router]);

  useEffect(() => {
    loadDevices();
    return () => messagingSocket.disconnect();
  }, [loadDevices]);

  async function handleLogout() {
    const refreshToken = await getRefreshToken();
    if (refreshToken) {
      await authApi.logout(refreshToken).catch(() => undefined);
    }
    messagingSocket.disconnect();
    await clearSession();
    router.replace("/");
  }

  async function handleLogoutEverywhere() {
    const accessToken = await getAccessToken();
    if (accessToken) {
      await authApi.logoutAll(accessToken).catch(() => undefined);
    }
    messagingSocket.disconnect();
    await clearSession();
    router.replace("/");
  }

  return (
    <Screen>
      <Text className="mb-2 mt-8 text-3xl font-semibold text-text-primary">Your devices</Text>
      <Text className="mb-8 text-base text-text-secondary">
        Every device signed in to your DITSALA account.
      </Text>

      {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}

      <Button
        testID="sos-nav-button"
        label="SOS"
        onPress={() => router.push("/sos")}
      />
      <View className="h-3" />
      <Button
        testID="circle-nav-button"
        label="Circle"
        onPress={() => router.push("/circle")}
        variant="secondary"
      />
      <View className="h-3" />

      <FlatList
        data={devices}
        keyExtractor={(item) => item.id}
        className="mb-8"
        renderItem={({ item }) => (
          <View className="mb-3 rounded border border-border bg-surface p-4">
            <Text className="text-base text-text-primary">{item.device_name}</Text>
            <Text className="text-sm text-text-tertiary">
              {item.platform} · {item.is_trusted ? "Trusted" : "Not trusted"}
            </Text>
          </View>
        )}
      />

      <Button testID="logout-button" label="Log out" onPress={handleLogout} variant="secondary" />
      <View className="h-3" />
      <Button
        testID="logout-all-button"
        label="Log out everywhere"
        onPress={handleLogoutEverywhere}
        variant="secondary"
      />
      <View className="h-3" />
      <Button
        testID="manage-account-button"
        label="Deactivate account"
        onPress={() => router.push("/account/deactivate")}
        variant="secondary"
      />
    </Screen>
  );
}
