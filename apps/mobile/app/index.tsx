import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Image, Platform, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Button } from "../components/Button";
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

// Same hero photo the reference design uses — a real Unsplash direct-
// image URL, not a bundled asset. Disclosed tradeoff: hotlinking a
// third-party image is fragile for a shipped app (no local control over
// availability); worth replacing with a licensed, bundled asset before
// this is the actual App Store build, not fixed here.
const HERO_URL =
  "https://images.unsplash.com/photo-1589483232748-515c025575bc?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjA1NTZ8MHwxfHNlYXJjaHwxfHxtb2Rlcm4lMjBkaXZlcnNlJTIwQWZyaWNhbiUyMGZyaWVuZHMlMjBsYXVnaGluZyUyMHBvcnRyYWl0JTIwcHJlbWl1bSUyMHBob3RvZ3JhcGh5fGVufDB8fHx8MTc5MDQzNDg1NHww&ixlib=rb-4.1.0&q=85";

/**
 * The screen every launch shows first — whether that's a first-time
 * visitor (Welcome: hero photo, brand, Get Started/Login) or a returning
 * one (Unlock: same hero backdrop, biometric/PIN instead of marketing
 * copy). Previously a plain centered-logo card on a flat background;
 * this is the real full-bleed hero-photo-plus-gradient treatment the
 * reference design uses, applied to both states so "opening the app"
 * looks the same regardless of which one a given user actually sees.
 */
export default function Welcome() {
  const router = useRouter();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
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
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <Image source={{ uri: HERO_URL }} style={StyleSheet.absoluteFill} resizeMode="cover" />
      <LinearGradient
        colors={["rgba(5,11,32,0.25)", "rgba(5,11,32,0.6)", "rgba(5,11,32,0.97)"]}
        locations={[0, 0.45, 1]}
        style={StyleSheet.absoluteFill}
      />

      <View
        style={{
          flex: 1,
          justifyContent: "space-between",
          paddingHorizontal: 24,
          paddingTop: insets.top + 32,
          paddingBottom: insets.bottom + 24,
        }}
      >
        <View className="items-center">
          <View
            className="h-16 w-16 items-center justify-center rounded-3xl bg-accent"
            style={{
              shadowColor: colors.accent,
              shadowOpacity: 0.5,
              shadowRadius: 20,
              shadowOffset: { width: 0, height: 10 },
              elevation: 8,
            }}
          >
            <Text className="text-3xl font-extrabold text-white">D</Text>
          </View>
        </View>

        <View>
          <Text className="text-5xl font-extrabold tracking-tight text-white">DITSALA</Text>
          <Text className="mt-2 text-lg font-bold italic" style={{ color: colors.gold }}>
            Your trusted circle.
          </Text>
          {!hasSession ? (
            <Text className="mt-3 text-base leading-6" style={{ color: "rgba(255,255,255,0.85)" }}>
              Private messaging, group calls, and real end-to-end encrypted conversations —
              speak with confidence.
            </Text>
          ) : null}

          <View className="mt-8">
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
                  label="Create account"
                  onPress={() => router.push("/onboarding/signup")}
                />
                <View className="h-3" />
                <Button
                  testID="already-have-account-button"
                  label="I already have an account"
                  variant="secondary"
                  onPress={() => router.push("/login")}
                />
              </>
            )}
          </View>
        </View>
      </View>
    </View>
  );
}
