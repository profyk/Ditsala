import { useRouter } from "expo-router";
import { useState } from "react";
import { Text } from "react-native";

import { Button } from "../../components/Button";
import { Screen } from "../../components/Screen";
import { TextField } from "../../components/TextField";
import { ApiError, onboardingApi } from "../../lib/api";
import { useOnboarding } from "../../lib/onboarding-context";
import { isStrongDitsalaCode } from "../../lib/validation";

export default function SetCode() {
  const router = useRouter();
  const { token, setAccountState } = useOnboarding();
  const [code, setCode] = useState("");
  const [confirmCode, setConfirmCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const codesMatch = code.length > 0 && code === confirmCode;
  const canSubmit = isStrongDitsalaCode(code) && codesMatch;

  async function handleSubmit() {
    if (!token) return;
    setError(null);
    setSubmitting(true);
    try {
      const result = await onboardingApi.setDitsalaCode(token, code);
      setAccountState(result.account_state);
      router.push("/onboarding/complete");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not set your DITSALA Code.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Screen>
      <Text className="mb-2 mt-8 text-3xl font-semibold text-text-primary">
        Set your DITSALA Code
      </Text>
      <Text className="mb-8 text-base text-text-secondary">
        At least 8 characters, including a number. You’ll use this alongside Face ID to sign in.
      </Text>

      <TextField
        label="DITSALA Code"
        value={code}
        onChangeText={setCode}
        secureTextEntry
        autoCapitalize="none"
        testID="ditsala-code-input"
      />
      <TextField
        label="Confirm DITSALA Code"
        value={confirmCode}
        onChangeText={setConfirmCode}
        secureTextEntry
        autoCapitalize="none"
        error={confirmCode.length > 0 && !codesMatch ? "Codes don't match." : undefined}
        testID="ditsala-code-confirm-input"
      />

      {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}

      <Button
        testID="set-code-submit-button"
        label="Continue"
        onPress={handleSubmit}
        loading={submitting}
        disabled={!canSubmit}
      />
    </Screen>
  );
}
