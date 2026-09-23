import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Platform, Text, View } from "react-native";

import { Button } from "../components/Button";
import { Screen } from "../components/Screen";
import { TextField } from "../components/TextField";
import { ApiError, authApi } from "../lib/api";
import { authenticateWithBiometrics, isBiometricAvailable } from "../lib/biometric";
import {
  clearSession,
  getIdentity,
  getRefreshToken,
  hasStoredSession,
  saveAccessToken,
  saveIdentity,
  saveSession,
} from "../lib/session";
import { useTheme } from "../lib/theme-context";

export default function Welcome() {
  const router = useRouter();
  const { colors } = useTheme();
  const [hasSession, setHasSession] = useState<boolean | null>(null);
  const [biometricsAvailable, setBiometricsAvailable] = useState<boolean | null>(null);
  const [pinMode, setPinMode] = useState(false);
  const [pin, setPin] = useState("");
  const [unlocking, setUnlocking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    hasStoredSession().then(setHasSession);
    isBiometricAvailable().then(setBiometricsAvailable);
  }, []);

  /**
   * Routine unlock (§17): the biometric prompt never leaves the device and
   * is not a substitute for the DITSALA Code server-side — it only gates
   * access to the refresh token already in SecureStore. The actual server
   * call below is a normal token refresh, not a fresh authentication
   * event. ADR 0014 adds a PIN fallback for when biometrics is
   * unavailable, declined, or fails — that path *is* a fresh, server-
   * verified authentication (`authApi.loginStart`), since there's no
   * locally-verifiable PIN to check against otherwise.
   */
  async function handleBiometricUnlock() {
    setError(null);
    setUnlocking(true);
    try {
      const refreshToken = await getRefreshToken();
      if (!refreshToken) {
        setHasSession(false);
        return;
      }
      const ok = await authenticateWithBiometrics("Unlock DITSALA");
      if (!ok) {
        setPinMode(true);
        return;
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

  async function handlePinUnlock() {
    setError(null);
    setUnlocking(true);
    try {
      const identity = await getIdentity();
      if (!identity) {
        // Older session predating locally-cached identity — the refresh
        // token alone still unlocks it.
        const refreshToken = await getRefreshToken();
        if (!refreshToken) {
          setHasSession(false);
          return;
        }
        const { access_token } = await authApi.refresh(refreshToken);
        await saveAccessToken(access_token);
        router.replace("/home");
        return;
      }
      const result = await authApi.loginStart(identity.identifier, pin, {
        device_name: Platform.OS === "ios" ? "iPhone" : "Android device",
        platform: Platform.OS === "ios" ? "ios" : "android",
        push_token: null,
      });
      if (result.access_token && result.refresh_token) {
        await saveSession(result.access_token, result.refresh_token);
        await saveIdentity(identity.identifier, identity.accountTier);
        router.replace("/home");
      } else if (result.requires_liveness) {
        // A vip-tier account shouldn't reach this screen's PIN path at
        // all (vip signs in with email + PIN via the full login screen,
        // not a persistent local unlock) — redirect there defensively.
        router.replace("/login");
      } else {
        setError("Incorrect PIN.");
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Incorrect PIN.");
    } finally {
      setUnlocking(false);
    }
  }

  return (
    <Screen scroll={false}>
      <View className="flex-1 items-center justify-center">
        <View
          className="mb-8 h-24 w-24 items-center justify-center rounded-3xl bg-accent"
          style={{
            shadowColor: colors.accent,
            shadowOpacity: 0.5,
            shadowRadius: 24,
            shadowOffset: { width: 0, height: 12 },
            elevation: 8,
          }}
        >
          <Text className="text-5xl font-extrabold text-white">D</Text>
        </View>
        <Text className="text-4xl font-extrabold tracking-tight text-text-primary">DITSALA</Text>
        <View className="mt-4 h-1 w-10 rounded-full bg-accent" />
        <Text className="mt-4 text-lg font-medium text-text-primary">Speak with Confidence.</Text>
        <Text className="mt-1 text-base text-text-secondary">Your trusted circle.</Text>
      </View>
      <View className="mb-8">
        {error ? <Text className="mb-4 text-center text-sm text-danger">{error}</Text> : null}
        {hasSession ? (
          pinMode || biometricsAvailable === false ? (
            <>
              <TextField
                label="DITSALA Code (PIN)"
                icon="lock"
                value={pin}
                onChangeText={setPin}
                secureTextEntry
                keyboardType="number-pad"
                maxLength={6}
                testID="unlock-pin-input"
              />
              <Button
                testID="unlock-with-pin-button"
                label="Unlock"
                onPress={handlePinUnlock}
                loading={unlocking}
                disabled={pin.length < 4}
              />
            </>
          ) : (
            <>
              <Button
                testID="unlock-button"
                label="Unlock"
                icon="lock"
                onPress={handleBiometricUnlock}
                loading={unlocking}
              />
              <View className="h-3" />
              <Button
                testID="use-pin-instead-button"
                label="Use PIN instead"
                variant="secondary"
                onPress={() => setPinMode(true)}
              />
            </>
          )
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
