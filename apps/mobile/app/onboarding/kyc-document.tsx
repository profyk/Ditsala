import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, Text, View } from "react-native";

import { Button } from "../../components/Button";
import { Screen } from "../../components/Screen";
import { ApiError, onboardingApi } from "../../lib/api";
import { useOnboarding } from "../../lib/onboarding-context";

type DocumentType = "sa_id" | "passport";

export default function KycDocument() {
  const router = useRouter();
  const { token, accountState, setAccountState } = useOnboarding();
  const [documentType, setDocumentType] = useState<DocumentType>("sa_id");
  const [captureStarted, setCaptureStarted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleStartCapture() {
    if (!token) return;
    setError(null);
    setSubmitting(true);
    try {
      // The Smile ID mobile SDK drives capture UX from here (native module +
      // Expo config plugin — docs/DITSALA_MASTER_SPEC.md §12), passed this
      // job's SDK token, and it talks to Smile ID directly (camera only,
      // no gallery). That native integration isn't built yet; this screen
      // requests the real backend job/token, but there is no capture UI
      // to launch it into. See CLAUDE.md "Phase 2" for the status of this gap.
      await onboardingApi.startKycDocument(token, documentType);
      setCaptureStarted(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start document capture.");
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
      if (status.account_state === "pending_kyc_liveness") {
        router.push("/onboarding/kyc-liveness");
      } else if (status.account_state === "manual_review") {
        setError("Your document needs manual review — we'll be in touch.");
      } else {
        setError("Still waiting on your document result. Check again shortly.");
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
        Verify your identity
      </Text>
      <Text className="mb-8 text-base text-text-secondary">
        We need a photo of your South African ID or passport, taken live with your camera —
        gallery photos aren’t accepted.
      </Text>

      {!captureStarted ? (
        <>
          <View className="mb-6 flex-row gap-3">
            {(["sa_id", "passport"] as const).map((type) => (
              <Pressable
                key={type}
                testID={`document-type-${type}`}
                onPress={() => setDocumentType(type)}
                className={[
                  "flex-1 items-center rounded-xl border py-3",
                  documentType === type
                    ? "border-accent bg-accent-muted"
                    : "border-border bg-surface",
                ].join(" ")}
              >
                <Text className="text-text-primary">
                  {type === "sa_id" ? "SA ID" : "Passport"}
                </Text>
              </Pressable>
            ))}
          </View>
          {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}
          <Button
            testID="start-kyc-document-button"
            label="Begin capture"
            onPress={handleStartCapture}
            loading={submitting}
          />
        </>
      ) : (
        <>
          <Text className="mb-6 text-base text-text-secondary">
            Verifying your document — this usually takes a few seconds.
          </Text>
          {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}
          <Button
            testID="check-kyc-status-button"
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
