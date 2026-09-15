import { useFocusEffect, useRouter } from "expo-router";
import * as Location from "expo-location";
import { useCallback, useEffect, useRef, useState } from "react";
import { FlatList, Text, View } from "react-native";

import { Button } from "../../components/Button";
import { Screen } from "../../components/Screen";
import { ApiError } from "../../lib/api";
import { circleApi, type Contact } from "../../lib/circle-api";
import { locationApi, type LocationShare } from "../../lib/location-api";
import { getAccessToken } from "../../lib/session";

const PING_INTERVAL_MS = 30_000;
const DURATION_PRESETS: { label: string; seconds: number }[] = [
  { label: "15 min", seconds: 15 * 60 },
  { label: "1 hour", seconds: 60 * 60 },
  { label: "8 hours", seconds: 8 * 60 * 60 },
];

/**
 * §25: location sharing is off by default and `trusted`-tier only. Real
 * GPS via expo-location while this screen is open — foreground-only
 * (no background location task registered), which is a deliberate MVP
 * scope, not a stub: see docs/SECURITY_GAPS.md.
 */
export default function LocationScreen() {
  const router = useRouter();
  const [trustedContacts, setTrustedContacts] = useState<Contact[]>([]);
  const [sharesByMe, setSharesByMe] = useState<LocationShare[]>([]);
  const [sharesToMe, setSharesToMe] = useState<LocationShare[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busyContactId, setBusyContactId] = useState<string | null>(null);
  const watchSubscriptions = useRef(new Map<string, Location.LocationSubscription>());

  const load = useCallback(async () => {
    const token = await getAccessToken();
    if (!token) {
      router.replace("/");
      return;
    }
    try {
      const [contacts, byMe, toMe] = await Promise.all([
        circleApi.listContacts(token),
        locationApi.listSharesByMe(token),
        locationApi.listSharesToMe(token),
      ]);
      setTrustedContacts(contacts.filter((c) => c.tier === "trusted"));
      setSharesByMe(byMe);
      setSharesToMe(toMe);
      setError(null);
    } catch {
      setError("Could not load location sharing.");
    }
  }, [router]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  useEffect(() => {
    const subscriptions = watchSubscriptions.current;
    return () => {
      for (const sub of subscriptions.values()) sub.remove();
      subscriptions.clear();
    };
  }, []);

  async function startWatching(shareId: string, token: string): Promise<void> {
    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status !== "granted") {
      setError("Location permission is needed to share your location.");
      return;
    }
    const subscription = await Location.watchPositionAsync(
      { accuracy: Location.LocationAccuracy.Balanced, timeInterval: PING_INTERVAL_MS },
      (position) => {
        void locationApi
          .recordPing(token, shareId, {
            lat: position.coords.latitude,
            lng: position.coords.longitude,
            accuracyM: position.coords.accuracy ?? 0,
          })
          .catch(() => undefined); // a dropped ping isn't fatal — the next one carries on
      }
    );
    watchSubscriptions.current.set(shareId, subscription);
  }

  async function handleShare(contactUserId: string, durationSeconds: number) {
    const token = await getAccessToken();
    if (!token) return;
    setBusyContactId(contactUserId);
    try {
      const share = await locationApi.createShare(token, contactUserId, durationSeconds);
      await startWatching(share.id, token);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start sharing.");
    } finally {
      setBusyContactId(null);
    }
  }

  async function handleRevoke(shareId: string) {
    const token = await getAccessToken();
    if (!token) return;
    watchSubscriptions.current.get(shareId)?.remove();
    watchSubscriptions.current.delete(shareId);
    try {
      await locationApi.revokeShare(token, shareId);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not stop sharing.");
    }
  }

  return (
    <Screen>
      <Text className="mb-2 mt-8 text-3xl font-semibold text-text-primary">Location</Text>
      <Text className="mb-6 text-base text-text-secondary">
        Off by default — only trusted Circle contacts, only for as long as you choose.
      </Text>

      {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}

      <Text className="mb-3 text-lg font-semibold text-text-primary">Sharing with</Text>
      <FlatList
        data={sharesByMe}
        keyExtractor={(item) => item.id}
        scrollEnabled={false}
        renderItem={({ item }) => (
          <View className="mb-3 rounded border border-border bg-surface p-4">
            <Text className="mb-3 text-sm text-text-tertiary">
              Until {new Date(item.expires_at).toLocaleString()}
            </Text>
            <Button
              testID={`revoke-share-${item.id}`}
              label="Stop sharing"
              variant="secondary"
              onPress={() => handleRevoke(item.id)}
            />
          </View>
        )}
        ListEmptyComponent={
          <Text className="mb-4 text-sm text-text-tertiary">Not sharing with anyone.</Text>
        }
      />

      <Text className="mb-3 mt-2 text-lg font-semibold text-text-primary">Shared with me</Text>
      <FlatList
        data={sharesToMe}
        keyExtractor={(item) => item.id}
        scrollEnabled={false}
        renderItem={({ item }) => (
          <View className="mb-3 rounded border border-border bg-surface p-4">
            <Text className="text-sm text-text-tertiary">
              Until {new Date(item.expires_at).toLocaleString()}
            </Text>
          </View>
        )}
        ListEmptyComponent={
          <Text className="mb-4 text-sm text-text-tertiary">
            No one is sharing their location with you.
          </Text>
        }
      />

      <Text className="mb-3 mt-2 text-lg font-semibold text-text-primary">
        Share your location
      </Text>
      <FlatList
        data={trustedContacts}
        keyExtractor={(item) => item.id}
        scrollEnabled={false}
        renderItem={({ item }) => (
          <View className="mb-3 rounded border border-border bg-surface p-4">
            <Text className="mb-3 text-base text-text-primary">{item.contact_display_name}</Text>
            <View className="flex-row gap-2">
              {DURATION_PRESETS.map((preset) => (
                <View key={preset.label} className="flex-1">
                  <Button
                    testID={`share-${item.contact_user_id}-${preset.seconds}`}
                    label={preset.label}
                    variant="secondary"
                    loading={busyContactId === item.contact_user_id}
                    onPress={() => handleShare(item.contact_user_id, preset.seconds)}
                  />
                </View>
              ))}
            </View>
          </View>
        )}
        ListEmptyComponent={
          <Text className="text-sm text-text-tertiary">
            Verify a contact into your Circle first — location can only be shared with trusted
            contacts.
          </Text>
        }
      />
    </Screen>
  );
}
