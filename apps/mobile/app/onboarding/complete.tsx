import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Platform, Text, View } from "react-native";

import { Button } from "../../components/Button";
import { Screen } from "../../components/Screen";
import { ApiError, authApi } from "../../lib/api";
import { useOnboarding } from "../../lib/onboarding-context";
import { saveIdentity, saveSession } from "../../lib/session";

/**
 * Device registration completes onboarding into `active`
 * (docs/DITSALA_MASTER_SPEC.md §9 step 8, §16-17) — this screen makes
 * that real call rather than just displaying state.
 */
export default function Complete() {
  const router = useRouter();
  const { token, accountState, setAccountState } = useOnboarding();
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function completeDeviceRegistration() {
    if (!token) return;
    setError(null);
    setSubmitting(true);
    try {
      const session = await authApi.completeOnboarding(token, {
        device_name: Platform.OS === "ios" ? "iPhone" : "Android device",
        platform: Platform.OS === "ios" ? "ios" : "android",
        push_token: null,
      });
      await saveSession(session.access_token, session.refresh_token);
      // Cache the login identifier + tier locally (ADR 0014) so future
      // app opens can offer a PIN unlock without asking for it again.
      const me = await authApi.getMe(session.access_token);
      await saveIdentity(me.identifier, me.account_tier);
      setAccountState("active");
      router.replace("/home");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not finish setting up this device.");
    } finally {
      setSubmitting(false);
    }
  }

  useEffect(() => {
    completeDeviceRegistration();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Screen scroll={false}>
      <View className="flex-1 items-center justify-center">
        <Text className="mb-3 text-3xl font-semibold text-text-primary">You’re almost there</Text>
        <Text className="text-center text-base text-text-secondary">
          Your identity is verified. Setting up your device finishes in a moment.
        </Text>
        <Text className="mt-6 text-xs text-text-tertiary">Status: {accountState}</Text>
        {error ? (
          <>
            <Text className="mt-6 text-center text-sm text-danger">{error}</Text>
            <View className="mt-4">
              <Button label="Try again" onPress={completeDeviceRegistration} loading={submitting} />
            </View>
          </>
        ) : null}
      </View>
    </Screen>
  );
}
