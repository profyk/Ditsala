import { useRouter } from "expo-router";
import { useState } from "react";
import { Text } from "react-native";

import { Button } from "../../components/Button";
import { Screen } from "../../components/Screen";
import { ApiError } from "../../lib/api";
import { recoveryApi } from "../../lib/recovery-api";
import { useRecovery } from "../../lib/recovery-context";

export default function RecoveryLiveness() {
  const router = useRouter();
  const { recoveryRequestId } = useRecovery();
  const [started, setStarted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleStart() {
    if (!recoveryRequestId) return;
    setError(null);
    setSubmitting(true);
    try {
      // Same native-SDK gap as onboarding/kyc-liveness.tsx: this requests a
      // real SmartSelfie Authentication job/token from the backend, but the
      // Smile ID SDK that would actually drive the capture isn't
      // integrated yet (see docs/adr/0005-e2ee-native-module-gap.md for the
      // same reasoning applied to a different native module).
      await recoveryApi.startLiveness(recoveryRequestId);
      setStarted(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start the liveness check.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Screen>
      <Text className="mb-2 mt-8 text-3xl font-semibold text-text-primary">
        Confirm it's really you
      </Text>
      <Text className="mb-8 text-base text-text-secondary">
        A SmartSelfie check matched against your original verification confirms you're the same
        person who set up this account.
      </Text>

      {!started ? (
        <>
          {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}
          <Button
            testID="recovery-start-liveness-button"
            label="Begin liveness check"
            onPress={handleStart}
            loading={submitting}
          />
        </>
      ) : (
        <>
          <Text className="mb-6 text-base text-text-secondary">
            Verifying — this usually takes a few seconds.
          </Text>
          <Button
            testID="recovery-liveness-continue-button"
            label="Continue"
            onPress={() => router.push("/recovery/complete")}
          />
        </>
      )}
    </Screen>
  );
}
