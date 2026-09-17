import { useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { FlatList, Text, View } from "react-native";

import { Button } from "../../components/Button";
import { Screen } from "../../components/Screen";
import { ApiError, authApi, type Device } from "../../lib/api";
import { getAccessToken } from "../../lib/session";

export default function Devices() {
  const router = useRouter();
  const [devices, setDevices] = useState<Device[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [revokingId, setRevokingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    const accessToken = await getAccessToken();
    if (!accessToken) {
      router.replace("/");
      return;
    }
    try {
      setDevices(await authApi.listDevices(accessToken));
    } catch {
      setError("Could not load your devices.");
    }
  }, [router]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleRevoke(deviceId: string) {
    const accessToken = await getAccessToken();
    if (!accessToken) return;
    setRevokingId(deviceId);
    try {
      await authApi.revokeDevice(accessToken, deviceId);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not sign out that device.");
    } finally {
      setRevokingId(null);
    }
  }

  return (
    <Screen>
      <Text className="mb-2 mt-8 text-3xl font-semibold text-text-primary">Devices</Text>
      <Text className="mb-6 text-base text-text-secondary">
        Every device signed in to your DITSALA account.
      </Text>

      {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}

      <FlatList
        data={devices.filter((d) => !d.revoked_at)}
        keyExtractor={(item) => item.id}
        renderItem={({ item }) => (
          <View className="mb-3 rounded-lg border border-border bg-surface p-4">
            <Text className="text-base text-text-primary">{item.device_name}</Text>
            <Text className="mb-3 text-sm text-text-tertiary">
              {item.platform} · {item.is_trusted ? "Trusted" : "Not trusted"}
            </Text>
            <Button
              testID={`revoke-device-${item.id}`}
              label="Sign out this device"
              variant="secondary"
              loading={revokingId === item.id}
              onPress={() => handleRevoke(item.id)}
            />
          </View>
        )}
        ListEmptyComponent={<Text className="text-sm text-text-tertiary">No devices found.</Text>}
      />
    </Screen>
  );
}
