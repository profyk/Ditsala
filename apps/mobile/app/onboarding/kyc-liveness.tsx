import { useRouter } from "expo-router";
import { useState } from "react";
import { Text } from "react-native";

import { Button } from "../../components/Button";
import { Screen } from "../../components/Screen";
import { ApiError, onboardingApi } from "../../lib/api";
import { useOnboarding } from "../../lib/onboarding-context";

export default function KycLiveness() {
  const router = useRouter();
  const { token, accountState, setAccountState } = useOnboarding();
  const [captureStarted, setCaptureStarted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleStartCapture() {
    if (!token) return;
    setError(null);
    setSubmitting(true);
    try {
      // Same native-SDK gap as kyc-document.tsx: this requests a real
      // SmartSelfie job/token from the backend, but the Smile ID SDK that
      // would actually drive the liveness capture isn't integrated yet.
      await onboardingApi.startKycLiveness(token);
      setCaptureStarted(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start liveness capture.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCheckStatus() {
    if (!token) return;
    setError(null);
    setSubmitting(true);
    try {
      const status = await onboardingApi.getStatus(token);
      setAccountState(status.account_state);
      if (status.account_state === "pending_next_of_kin") {
        router.push("/onboarding/next-of-kin");
      } else if (status.account_state === "manual_review") {
        setError("We need to manually review your verification — we'll be in touch.");
      } else {
        setError("Still waiting on your liveness result. Check again shortly.");
      }
    } catch {
      setError("Could not check status — try again shortly.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Screen>
      <Text className="mb-2 mt-8 text-3xl font-semibold text-text-primary">
        Confirm it’s really you
      </Text>
      <Text className="mb-8 text-base text-text-secondary">
        A quick SmartSelfie liveness check confirms the face in your document is really you,
        live, right now.
      </Text>

      {!captureStarted ? (
        <>
          {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}
          <Button
            testID="start-kyc-liveness-button"
            label="Begin liveness check"
            onPress={handleStartCapture}
            loading={submitting}
          />
        </>
      ) : (
        <>
          <Text className="mb-6 text-base text-text-secondary">
            Verifying your liveness — this usually takes a few seconds.
          </Text>
          {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}
          <Button
            testID="check-liveness-status-button"
            label="Check status"
            onPress={handleCheckStatus}
            loading={submitting}
          />
        </>
      )}
      <Text className="mt-6 text-xs text-text-tertiary">Current status: {accountState}</Text>
    </Screen>
  );
}
