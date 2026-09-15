import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, Text } from "react-native";

import { Button } from "../../components/Button";
import { Screen } from "../../components/Screen";
import { TextField } from "../../components/TextField";
import { ApiError, onboardingApi } from "../../lib/api";
import { useOnboarding } from "../../lib/onboarding-context";

export default function VerifyEmail() {
  const router = useRouter();
  const { token, setAccountState } = useOnboarding();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleConfirm() {
    if (!token) return;
    setError(null);
    setSubmitting(true);
    try {
      const result = await onboardingApi.confirmEmail(token, code.trim());
      setAccountState(result.account_state);
      router.push("/onboarding/verify-phone");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not verify that code.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleResend() {
    if (!token) return;
    setError(null);
    try {
      await onboardingApi.resendEmailCode(token);
      setInfo("A new code is on its way.");
    } catch {
      setError("Could not resend a code — try again shortly.");
    }
  }

  return (
    <Screen>
      <Text className="mb-2 mt-8 text-3xl font-semibold text-text-primary">Check your email</Text>
      <Text className="mb-8 text-base text-text-secondary">
        Enter the 6-digit code we sent you. It expires in 10 minutes.
      </Text>

      <TextField
        label="Verification code"
        value={code}
        onChangeText={setCode}
        keyboardType="number-pad"
        maxLength={6}
        testID="email-code-input"
      />

      {info ? <Text className="mb-4 text-sm text-text-secondary">{info}</Text> : null}
      {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}

      <Button
        testID="confirm-email-button"
        label="Confirm"
        onPress={handleConfirm}
        loading={submitting}
        disabled={code.trim().length < 4}
      />
      <Pressable className="mt-4 items-center py-2" onPress={handleResend}>
        <Text className="text-sm text-accent">Resend code</Text>
      </Pressable>
    </Screen>
  );
}
