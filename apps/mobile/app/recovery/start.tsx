import { useRouter } from "expo-router";
import { useState } from "react";
import { Text } from "react-native";

import { Button } from "../../components/Button";
import { Screen } from "../../components/Screen";
import { TextField } from "../../components/TextField";
import { ApiError } from "../../lib/api";
import { recoveryApi } from "../../lib/recovery-api";
import { useRecovery } from "../../lib/recovery-context";

export default function RecoveryStart() {
  const router = useRouter();
  const { setRecoveryRequestId } = useRecovery();
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleStart() {
    setError(null);
    setSubmitting(true);
    try {
      const result = await recoveryApi.start(email.trim(), phone.trim());
      setRecoveryRequestId(result.id);
      router.push("/recovery/confirm-email");
    } catch (err) {
      // Deliberately the same message whether nothing matched or something
      // else went wrong — this endpoint must not be usable to enumerate
      // which emails/phones have an account (see backend RecoveryService).
      setError(
        err instanceof ApiError ? err.message : "Could not start recovery — try again shortly."
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Screen>
      <Text className="mb-2 mt-8 text-3xl font-semibold text-text-primary">
        Recover your account
      </Text>
      <Text className="mb-8 text-base text-text-secondary">
        Enter the email and phone number on your account. We'll re-verify both, then confirm it's
        really you with a liveness check.
      </Text>

      <TextField
        label="Email"
        value={email}
        onChangeText={setEmail}
        autoCapitalize="none"
        keyboardType="email-address"
        testID="recovery-email-input"
      />
      <TextField
        label="Phone number"
        value={phone}
        onChangeText={setPhone}
        keyboardType="phone-pad"
        testID="recovery-phone-input"
      />

      {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}

      <Button
        testID="recovery-start-button"
        label="Continue"
        onPress={handleStart}
        loading={submitting}
        disabled={email.trim().length === 0 || phone.trim().length === 0}
      />
    </Screen>
  );
}
