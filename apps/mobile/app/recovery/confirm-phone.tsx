import { useRouter } from "expo-router";
import { useState } from "react";
import { Text } from "react-native";

import { Button } from "../../components/Button";
import { Screen } from "../../components/Screen";
import { TextField } from "../../components/TextField";
import { ApiError } from "../../lib/api";
import { recoveryApi } from "../../lib/recovery-api";
import { useRecovery } from "../../lib/recovery-context";

export default function RecoveryConfirmPhone() {
  const router = useRouter();
  const { recoveryRequestId } = useRecovery();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleConfirm() {
    if (!recoveryRequestId) return;
    setError(null);
    setSubmitting(true);
    try {
      await recoveryApi.confirmPhone(recoveryRequestId, code.trim());
      router.push("/recovery/liveness");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not verify that code.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Screen>
      <Text className="mb-2 mt-8 text-3xl font-semibold text-text-primary">Check your phone</Text>
      <Text className="mb-8 text-base text-text-secondary">
        Enter the 6-digit code we texted you.
      </Text>

      <TextField
        label="Verification code"
        value={code}
        onChangeText={setCode}
        keyboardType="number-pad"
        maxLength={6}
        testID="recovery-phone-code-input"
      />

      {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}

      <Button
        testID="recovery-confirm-phone-button"
        label="Confirm"
        onPress={handleConfirm}
        loading={submitting}
        disabled={code.trim().length < 4}
      />
    </Screen>
  );
}
