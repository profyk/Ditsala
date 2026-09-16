import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Text, View } from "react-native";

import { Button } from "../components/Button";
import { Screen } from "../components/Screen";
import { authApi } from "../lib/api";
import { authenticateWithBiometrics, isBiometricAvailable } from "../lib/biometric";
import { clearSession, getRefreshToken, hasStoredSession, saveAccessToken } from "../lib/session";

export default function Welcome() {
  const router = useRouter();
  const [hasSession, setHasSession] = useState<boolean | null>(null);
  const [unlocking, setUnlocking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    hasStoredSession().then(setHasSession);
  }, []);

  async function handleUnlock() {
    setError(null);
    setUnlocking(true);
    try {
      const refreshToken = await getRefreshToken();
      if (!refreshToken) {
        setHasSession(false);
        return;
      }
      // Routine unlock (§17): the biometric prompt never leaves the
      // device and is not a substitute for the DITSALA Code server-side —
      // it only gates access to the refresh token already in SecureStore.
      // The actual server call below is a normal token refresh, not a
      // fresh authentication event.
      const available = await isBiometricAvailable();
      if (available) {
        const ok = await authenticateWithBiometrics("Unlock DITSALA");
        if (!ok) {
          setError("Unlock cancelled.");
          return;
        }
      }
      const { access_token } = await authApi.refresh(refreshToken);
      await saveAccessToken(access_token);
      router.replace("/home");
    } catch {
      // Refresh token was rejected (expired/revoked) — fall back to a full login.
      await clearSession();
      setHasSession(false);
    } finally {
      setUnlocking(false);
    }
  }

  return (
    <Screen scroll={false}>
      <View className="flex-1 items-center justify-center">
        <View className="mb-8 h-20 w-20 items-center justify-center rounded-full border border-accent/50 bg-accent-muted">
          {/* Brand type scale calls for Fraunces here (packages/ui-tokens'
              `fontFamily.display`) — not wired into this RN app yet (no
              font asset loading set up), so this uses the system font's
              own bold weight rather than silently claiming a typeface
              that isn't actually loaded. See docs/SECURITY_GAPS.md. */}
          <Text className="text-4xl font-bold text-accent">D</Text>
        </View>
        <Text className="text-5xl font-semibold tracking-wide text-text-primary">DITSALA</Text>
        <View className="mt-4 h-px w-12 bg-accent" />
        <Text className="mt-4 text-lg text-text-primary">Speak with Confidence.</Text>
        <Text className="mt-1 text-base text-text-secondary">Your trusted circle.</Text>
      </View>
      <View className="mb-8">
        {error ? <Text className="mb-4 text-center text-sm text-danger">{error}</Text> : null}
        {hasSession ? (
          <>
            <Button
              testID="unlock-button"
              label="Unlock"
              onPress={handleUnlock}
              loading={unlocking}
            />
            <View className="h-3" />
            <Button
              testID="login-differently-button"
              label="Sign in differently"
              variant="secondary"
              onPress={() => router.push("/login")}
            />
          </>
        ) : (
          <>
            <Button
              testID="get-started-button"
              label="Get Started"
              onPress={() => router.push("/onboarding/signup")}
            />
            <View className="my-4 flex-row items-center gap-3">
              <View className="h-px flex-1 bg-border" />
              <Text className="text-xs font-medium uppercase tracking-widest text-text-tertiary">
                or
              </Text>
              <View className="h-px flex-1 bg-border" />
            </View>
            <Button
              testID="already-have-account-button"
              label="I already have an account"
              variant="secondary"
              onPress={() => router.push("/login")}
            />
          </>
        )}
      </View>
    </Screen>
  );
}
