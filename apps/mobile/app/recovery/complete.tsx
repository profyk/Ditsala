import { useRouter } from "expo-router";
import { useState } from "react";
import { Platform, Text } from "react-native";

import { Button } from "../../components/Button";
import { Screen } from "../../components/Screen";
import { TextField } from "../../components/TextField";
import { ApiError } from "../../lib/api";
import { recoveryApi } from "../../lib/recovery-api";
import { useRecovery } from "../../lib/recovery-context";
import { saveSession } from "../../lib/session";

export default function RecoveryComplete() {
  const router = useRouter();
  const { recoveryRequestId, clear } = useRecovery();
  const [newCode, setNewCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleComplete() {
    if (!recoveryRequestId) return;
    setError(null);
    setSubmitting(true);
    try {
      const session = await recoveryApi.complete({
        recoveryRequestId,
        newDitsalaCode: newCode,
        deviceName: Platform.OS === "ios" ? "iPhone" : "Android device",
        platform: Platform.OS === "ios" ? "ios" : "android",
        pushToken: null,
      });
      await saveSession(session.access_token, session.refresh_token);
      clear();
      router.replace("/home");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not finish recovery — try checking again shortly."
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Screen>
      <Text className="mb-2 mt-8 text-3xl font-semibold text-text-primary">
        Set a new DITSALA Code
      </Text>
      <Text className="mb-8 text-base text-text-secondary">
        This replaces your old code and signs you in on this device. Every other device on your
        account will be signed out.
      </Text>

      <TextField
        label="New DITSALA Code"
        value={newCode}
        onChangeText={setNewCode}
        secureTextEntry
        autoCapitalize="none"
        testID="recovery-new-code-input"
      />

      {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}

      <Button
        testID="recovery-complete-button"
        label="Finish"
        onPress={handleComplete}
        loading={submitting}
        disabled={newCode.length < 8}
      />
    </Screen>
  );
}
