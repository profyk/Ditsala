import { useRouter } from "expo-router";
import { useState } from "react";
import { Platform, Text } from "react-native";

import { Button } from "../components/Button";
import { Screen } from "../components/Screen";
import { TextField } from "../components/TextField";
import { ApiError, authApi } from "../lib/api";
import { saveSession } from "../lib/session";

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
      setLoginToken(result.login_token);
      setAwaitingLiveness(true);
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
      <Text className="mb-2 mt-8 text-3xl font-semibold text-text-primary">Sign in</Text>
      <Text className="mb-8 text-base text-text-secondary">
        Every full sign-in needs your DITSALA Code and a fresh liveness check — never just one.
      </Text>

      {!awaitingLiveness ? (
        <>
          <TextField
            label="Email or phone"
            value={identifier}
            onChangeText={setIdentifier}
            autoCapitalize="none"
            testID="login-identifier-input"
          />
          <TextField
            label="DITSALA Code"
            value={code}
            onChangeText={setCode}
            secureTextEntry
            autoCapitalize="none"
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
        </>
      ) : (
        <>
          <Text className="mb-6 text-base text-text-secondary">
            Confirming it’s really you — this usually takes a few seconds.
          </Text>
          {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}
          <Button
            testID="login-check-liveness-button"
            label="Check status"
            onPress={handleCheckLiveness}
            loading={submitting}
          />
        </>
      )}
    </Screen>
  );
}
