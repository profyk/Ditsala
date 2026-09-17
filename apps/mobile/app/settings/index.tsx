import { dark } from "@ditsala/ui-tokens";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable, Text, View } from "react-native";

import { Icon, type IconName } from "../../components/Icon";
import { TabScreen } from "../../components/TabScreen";
import { authApi } from "../../lib/api";
import { clearSession, getAccessToken, getRefreshToken } from "../../lib/session";

interface SettingsRowProps {
  testID: string;
  label: string;
  description?: string;
  icon: IconName;
  onPress: () => void;
  destructive?: boolean;
}

function SettingsRow({ testID, label, description, icon, onPress, destructive }: SettingsRowProps) {
  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      className="mb-2 flex-row items-center gap-3 rounded-xl border border-border bg-surface p-4 active:bg-surface-raised"
    >
      <View
        className="h-9 w-9 items-center justify-center rounded-full"
        style={{ backgroundColor: destructive ? `${dark.danger}22` : dark.accentMuted }}
      >
        <Icon name={icon} size={18} color={destructive ? dark.danger : dark.accent} />
      </View>
      <View className="flex-1">
        <Text className={`text-base font-medium ${destructive ? "text-danger" : "text-text-primary"}`}>
          {label}
        </Text>
        {description ? (
          <Text className="mt-0.5 text-xs text-text-tertiary">{description}</Text>
        ) : null}
      </View>
      <Icon name="chevron-right" size={16} color={dark.textTertiary} />
    </Pressable>
  );
}

/** A real settings hub — every row here calls a working backend
 * endpoint, nothing is a placeholder that looks functional but isn't. */
export default function Settings() {
  const router = useRouter();
  // ADR 0014 (§14): normal-tier accounts have no explicit login/logout —
  // "just exit" — so the routine "Log out" row only makes sense for vip.
  // Defaults to hidden until we know the tier, rather than flashing it.
  const [accountTier, setAccountTier] = useState<"normal" | "vip" | null>(null);

  useEffect(() => {
    getAccessToken().then((accessToken) => {
      if (!accessToken) return;
      authApi
        .getMe(accessToken)
        .then((me) => setAccountTier(me.account_tier))
        .catch(() => undefined);
    });
  }, []);

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
    <TabScreen>
      <Text className="mb-6 mt-4 text-2xl font-bold text-text-primary">Settings</Text>

      <Text className="mb-2 text-xs font-medium uppercase tracking-widest text-text-tertiary">
        Account
      </Text>
      <SettingsRow
        testID="settings-profile-row"
        label="Profile picture"
        description="Change or remove your photo"
        icon="camera"
        onPress={() => router.push("/account/profile")}
      />
      <SettingsRow
        testID="settings-devices-row"
        label="Devices"
        description="Manage where you're signed in"
        icon="phone"
        onPress={() => router.push("/settings/devices")}
      />
      <SettingsRow
        testID="settings-deactivate-row"
        label="Deactivate account"
        description="Reversible for 30 days"
        icon="close"
        onPress={() => router.push("/account/deactivate")}
      />

      <Text className="mb-2 mt-6 text-xs font-medium uppercase tracking-widest text-text-tertiary">
        Session
      </Text>
      {accountTier === "vip" ? (
        <SettingsRow
          testID="settings-logout-row"
          label="Log out"
          icon="logout"
          onPress={handleLogout}
        />
      ) : null}
      <SettingsRow
        testID="settings-logout-all-row"
        label="Log out everywhere"
        description="Revoke every device — useful if one is lost or stolen"
        icon="lock"
        onPress={handleLogoutEverywhere}
        destructive
      />
    </TabScreen>
  );
}
