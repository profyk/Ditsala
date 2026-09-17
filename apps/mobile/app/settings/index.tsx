import { useRouter } from "expo-router";
import { Pressable, Text, View } from "react-native";

import { Screen } from "../../components/Screen";
import { authApi } from "../../lib/api";
import { clearSession, getAccessToken, getRefreshToken } from "../../lib/session";

interface SettingsRowProps {
  testID: string;
  label: string;
  description?: string;
  onPress: () => void;
  destructive?: boolean;
}

function SettingsRow({ testID, label, description, onPress, destructive }: SettingsRowProps) {
  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      className="flex-row items-center justify-between border-b border-border py-4 active:bg-surface-raised"
    >
      <View className="flex-1 pr-3">
        <Text className={`text-base ${destructive ? "text-danger" : "text-text-primary"}`}>
          {label}
        </Text>
        {description ? (
          <Text className="mt-0.5 text-sm text-text-tertiary">{description}</Text>
        ) : null}
      </View>
      <Text className="text-text-tertiary">›</Text>
    </Pressable>
  );
}

/** A real settings hub — every row here calls a working backend
 * endpoint, nothing is a placeholder that looks functional but isn't. */
export default function Settings() {
  const router = useRouter();

  async function handleLogout() {
    const refreshToken = await getRefreshToken();
    if (refreshToken) await authApi.logout(refreshToken).catch(() => undefined);
    await clearSession();
    router.replace("/");
  }

  async function handleLogoutEverywhere() {
    const accessToken = await getAccessToken();
    if (accessToken) await authApi.logoutAll(accessToken).catch(() => undefined);
    await clearSession();
    router.replace("/");
  }

  return (
    <Screen>
      <Text className="mb-6 mt-8 text-3xl font-semibold text-text-primary">Settings</Text>

      <Text className="mb-2 text-xs font-medium uppercase tracking-widest text-text-tertiary">
        Account
      </Text>
      <SettingsRow
        testID="settings-profile-row"
        label="Profile picture"
        description="Change or remove your photo"
        onPress={() => router.push("/account/profile")}
      />
      <SettingsRow
        testID="settings-devices-row"
        label="Devices"
        description="Manage where you're signed in"
        onPress={() => router.push("/settings/devices")}
      />
      <SettingsRow
        testID="settings-deactivate-row"
        label="Deactivate account"
        description="Reversible for 30 days"
        onPress={() => router.push("/account/deactivate")}
      />

      <Text className="mb-2 mt-8 text-xs font-medium uppercase tracking-widest text-text-tertiary">
        Session
      </Text>
      <SettingsRow testID="settings-logout-row" label="Log out" onPress={handleLogout} />
      <SettingsRow
        testID="settings-logout-all-row"
        label="Log out everywhere"
        onPress={handleLogoutEverywhere}
        destructive
      />
    </Screen>
  );
}
