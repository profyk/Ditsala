import { useRouter } from "expo-router";
import { useState } from "react";
import { Platform, Pressable, Text, View } from "react-native";

import { Button } from "../components/Button";
import { Screen } from "../components/Screen";
import { TextField } from "../components/TextField";
import { ApiError, authApi } from "../lib/api";
import { saveIdentity, saveSession } from "../lib/session";

/**
 * ADR 0012 — this screen now branches on `requires_liveness`: a `vip`
 * account still needs a fresh SmartSelfie check after the code, but a
 * `normal` account (the default for every real signup today) gets a
 * session the moment the code checks out. Previously this screen assumed
 * every login needed a liveness step, which meant a normal-tier login
 * response's `access_token`/`refresh_token` were simply ignored — never
 * saved, never used to sign the user in.
 */
export default function Login() {
  const router = useRouter();
  const [identifier, setIdentifier] = useState("");
  const [code, setCode] = useState("");
  const [awaitingLiveness, setAwaitingLiveness] = useState(false);
  const [loginToken, setLoginToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleStart() {
    setError(null);
    setSubmitting(true);
    try {
      const result = await authApi.loginStart(identifier.trim(), code, {
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
        <View className="h-11 w-11 items-center justify-center rounded-full border border-accent/40 bg-accent-muted">
          <Text className="text-lg font-bold text-accent">D</Text>
        </View>
        <Text className="text-3xl font-semibold tracking-tight text-text-primary">Sign in</Text>
      </View>
      <Text className="mb-8 text-base leading-6 text-text-secondary">
        {awaitingLiveness
          ? "Confirming it's really you."
          : "Enter your DITSALA Code to continue. Circle members verified with liveness will confirm a fresh check next."}
      </Text>

      {!awaitingLiveness ? (
        <>
          <TextField
            label="Email or phone"
            value={identifier}
            onChangeText={setIdentifier}
            autoCapitalize="none"
            placeholder="you@example.com"
            testID="login-identifier-input"
          />
          <TextField
            label="DITSALA Code"
            value={code}
            onChangeText={setCode}
            secureTextEntry
            autoCapitalize="none"
            placeholder="••••••••"
            testID="login-code-input"
          />
          {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}
          <Button
            testID="login-start-button"
            label="Continue"
            onPress={handleStart}
            loading={submitting}
            disabled={identifier.trim().length === 0 || code.length === 0}
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
