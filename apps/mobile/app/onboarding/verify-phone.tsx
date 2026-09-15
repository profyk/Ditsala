import { useRouter } from "expo-router";
import { useState } from "react";
import { Text } from "react-native";

import { Button } from "../../components/Button";
import { Screen } from "../../components/Screen";
import { TextField } from "../../components/TextField";
import { ApiError, onboardingApi } from "../../lib/api";
import { useOnboarding } from "../../lib/onboarding-context";

export default function VerifyPhone() {
  const router = useRouter();
  const { token, setAccountState } = useOnboarding();
  const [codeSent, setCodeSent] = useState(false);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSendCode() {
    if (!token) return;
    setError(null);
    setSubmitting(true);
    try {
      await onboardingApi.requestPhoneCode(token);
      setCodeSent(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not send a code.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleConfirm() {
    if (!token) return;
    setError(null);
    setSubmitting(true);
    try {
      const result = await onboardingApi.confirmPhone(token, code.trim());
      setAccountState(result.account_state);
      router.push("/onboarding/kyc-document");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not verify that code.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Screen>
      <Text className="mb-2 mt-8 text-3xl font-semibold text-text-primary">Verify your phone</Text>
      <Text className="mb-8 text-base text-text-secondary">
        We’ll text you a code via SMS to confirm your number.
      </Text>

      {!codeSent ? (
        <Button
          testID="send-phone-code-button"
          label="Send code"
          onPress={handleSendCode}
          loading={submitting}
        />
      ) : (
        <>
          <TextField
            label="Verification code"
            value={code}
            onChangeText={setCode}
            keyboardType="number-pad"
            maxLength={6}
            testID="phone-code-input"
          />
          {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}
          <Button
            testID="confirm-phone-button"
            label="Confirm"
            onPress={handleConfirm}
            loading={submitting}
            disabled={code.trim().length < 4}
          />
        </>
      )}
    </Screen>
  );
}
