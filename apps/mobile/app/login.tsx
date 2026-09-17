import { dark } from "@ditsala/ui-tokens";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Platform, Pressable, Text, TextInput, View } from "react-native";

import { Button } from "../components/Button";
import { CountryCodePicker } from "../components/CountryCodePicker";
import { Screen } from "../components/Screen";
import { TextField } from "../components/TextField";
import { ApiError, authApi } from "../lib/api";
import { DEFAULT_COUNTRY, toE164, type Country } from "../lib/countries";
import { saveIdentity, saveSession } from "../lib/session";

type LoginMode = "phone" | "email";

/**
 * ADR 0012/0014 — this screen branches on `requires_liveness`: a `vip`
 * account still needs a fresh SmartSelfie check after the code, but a
 * `normal` account (the default for every real signup today) gets a
 * session the moment the code checks out. `normal` signs in with phone +
 * PIN (no email exists for that tier); `vip` signs in with email + PIN —
 * a phone/email toggle picks the right input shape instead of one
 * ambiguous free-text field, since a bare local number (no country code)
 * silently fails to match the stored E.164 phone and just looks like a
 * wrong PIN.
 */
export default function Login() {
  const router = useRouter();
  const [mode, setMode] = useState<LoginMode>("phone");
  const [country, setCountry] = useState<Country>(DEFAULT_COUNTRY);
  const [localNumber, setLocalNumber] = useState("");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [codeVisible, setCodeVisible] = useState(false);
  const [awaitingLiveness, setAwaitingLiveness] = useState(false);
  const [loginToken, setLoginToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const digitsOnly = localNumber.replace(/\D/g, "");
  const identifier = mode === "phone" ? toE164(country, localNumber) : email.trim();
  const canSubmit =
    (mode === "phone" ? digitsOnly.length >= 6 : email.trim().length > 0) &&
    code.length > 0;

  async function handleStart() {
    setError(null);
    setSubmitting(true);
    try {
      const result = await authApi.loginStart(identifier, code, {
        device_name: Platform.OS === "ios" ? "iPhone" : "Android device",
        platform: Platform.OS === "ios" ? "ios" : "android",
        push_token: null,
      });
      if (result.requires_liveness) {
        setLoginToken(result.login_token);
        setAwaitingLiveness(true);
      } else if (result.access_token && result.refresh_token) {
        await saveSession(result.access_token, result.refresh_token);
        const me = await authApi.getMe(result.access_token);
        await saveIdentity(me.identifier, me.account_tier);
        router.replace("/home");
      } else {
        setError("Something unexpected happened. Please try again.");
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not sign you in.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCheckLiveness() {
    if (!loginToken) return;
    setError(null);
    setSubmitting(true);
    try {
      const session = await authApi.loginComplete(loginToken);
      await saveSession(session.access_token, session.refresh_token);
      const me = await authApi.getMe(session.access_token);
      await saveIdentity(me.identifier, me.account_tier);
      router.replace("/home");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not complete sign-in — try checking again shortly."
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Screen>
      <View className="mt-10 mb-2 flex-row items-center gap-3">
        <View className="h-11 w-11 items-center justify-center rounded-2xl bg-accent">
          <Text className="text-lg font-extrabold text-white">D</Text>
        </View>
        <Text className="text-3xl font-extrabold tracking-tight text-text-primary">Sign in</Text>
      </View>
      <Text className="mb-8 text-base leading-6 text-text-secondary">
        {awaitingLiveness
          ? "Confirming it's really you."
          : "Enter your DITSALA Code to continue. Circle members verified with liveness will confirm a fresh check next."}
      </Text>

      {!awaitingLiveness ? (
        <>
          <View className="mb-5 flex-row overflow-hidden rounded-xl border border-border">
            <Pressable
              testID="login-mode-phone"
              onPress={() => setMode("phone")}
              className={`flex-1 items-center py-2.5 ${mode === "phone" ? "bg-accent-muted" : "bg-surface"}`}
            >
              <Text
                className={`text-sm font-semibold ${mode === "phone" ? "text-accent" : "text-text-secondary"}`}
              >
                Phone
              </Text>
            </Pressable>
            <Pressable
              testID="login-mode-email"
              onPress={() => setMode("email")}
              className={`flex-1 items-center py-2.5 ${mode === "email" ? "bg-accent-muted" : "bg-surface"}`}
            >
              <Text
                className={`text-sm font-semibold ${mode === "email" ? "text-accent" : "text-text-secondary"}`}
              >
                Email (VIP)
              </Text>
            </Pressable>
          </View>

          {mode === "phone" ? (
            <View className="mb-5">
              <Text className="mb-2 text-sm font-medium text-text-secondary">Phone number</Text>
              <View className="flex-row items-center">
                <CountryCodePicker
                  value={country}
                  onChange={setCountry}
                  testID="login-country-code-picker"
                />
                <TextInput
                  value={localNumber}
                  onChangeText={setLocalNumber}
                  placeholder="82 123 4567"
                  placeholderTextColor={dark.textTertiary}
                  keyboardType="number-pad"
                  testID="login-phone-input"
                  className="flex-1 rounded-xl border border-border bg-surface px-4 py-3 text-base text-text-primary"
                />
              </View>
            </View>
          ) : (
            <TextField
              label="Email"
              value={email}
              onChangeText={setEmail}
              autoCapitalize="none"
              keyboardType="email-address"
              placeholder="you@example.com"
              testID="login-email-input"
            />
          )}

          <View className="mb-5">
            <Text className="mb-2 text-sm font-medium text-text-secondary">DITSALA Code</Text>
            <View className="relative">
              <TextInput
                value={code}
                onChangeText={setCode}
                secureTextEntry={!codeVisible}
                autoCapitalize="none"
                placeholder="••••••••"
                placeholderTextColor={dark.textTertiary}
                testID="login-code-input"
                className="rounded-xl border border-border bg-surface px-4 py-3 pr-16 text-base text-text-primary"
              />
              <Pressable
                testID="login-code-visibility-toggle"
                onPress={() => setCodeVisible((v) => !v)}
                className="absolute bottom-0 right-0 top-0 items-center justify-center px-4"
              >
                <Text className="text-xs font-semibold text-accent">
                  {codeVisible ? "Hide" : "Show"}
                </Text>
              </Pressable>
            </View>
          </View>

          {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}
          <Button
            testID="login-start-button"
            label="Continue"
            onPress={handleStart}
            loading={submitting}
            disabled={!canSubmit}
          />
          <Pressable
            className="mt-5 items-center py-2"
            onPress={() => router.push("/recovery/start")}
          >
            <Text className="text-sm font-medium text-accent">
              Forgot your code or lost your device?
            </Text>
          </Pressable>
        </>
      ) : (
        <View className="items-center rounded-lg border border-border bg-surface px-6 py-8">
          <View className="mb-4 h-14 w-14 items-center justify-center rounded-full bg-accent-muted">
            <Text className="text-2xl">🔒</Text>
          </View>
          <Text className="mb-6 text-center text-base text-text-secondary">
            Confirming it&apos;s really you — this usually takes a few seconds.
          </Text>
          {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}
          <View className="w-full">
            <Button
              testID="login-check-liveness-button"
              label="Check status"
              onPress={handleCheckLiveness}
              loading={submitting}
            />
          </View>
        </View>
      )}
    </Screen>
  );
}
