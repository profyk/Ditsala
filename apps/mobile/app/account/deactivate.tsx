import { useRouter } from "expo-router";
import { useState } from "react";
import { Text } from "react-native";

import { Button } from "../../components/Button";
import { Screen } from "../../components/Screen";
import { accountApi } from "../../lib/account-api";
import { ApiError } from "../../lib/api";
import { clearSession, getAccessToken } from "../../lib/session";

/**
 * §14/§34.2 self-service deactivation — a 30-day reversible grace window,
 * not an immediate irreversible delete. This screen only starts that
 * window and signs the device out; cancelling within the window happens
 * by signing back in (§17's one uniform login flow) and calling
 * `/account/deactivate/cancel` — no dedicated "reactivate" screen exists
 * yet since login itself is the natural place a returning user lands.
 */
export default function DeactivateAccount() {
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleDeactivate() {
    setError(null);
    setSubmitting(true);
    try {
      const accessToken = await getAccessToken();
      if (!accessToken) {
        router.replace("/");
        return;
      }
      await accountApi.deactivate(accessToken);
      await clearSession();
      router.replace("/");
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not deactivate your account right now."
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCancelDeactivation() {
    setError(null);
    setSubmitting(true);
    try {
      const accessToken = await getAccessToken();
      if (!accessToken) {
        router.replace("/");
        return;
      }
      await accountApi.cancelDeactivation(accessToken);
      router.replace("/home");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not reactivate your account — it may not be deactivated."
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Screen>
      <Text className="mb-2 mt-8 text-3xl font-semibold text-text-primary">
        Deactivate your account
      </Text>
      <Text className="mb-8 text-base text-text-secondary">
        Your account and data are hidden immediately. You have 30 days to change your mind by
        signing back in — after that, everything is permanently deleted and cannot be recovered.
      </Text>

      {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}

      {!confirming ? (
        <Button
          testID="deactivate-account-button"
          label="Deactivate my account"
          onPress={() => setConfirming(true)}
          variant="secondary"
        />
      ) : (
        <>
          <Text className="mb-4 text-sm text-text-secondary">
            Are you sure? This signs you out of this device immediately.
          </Text>
          <Button
            testID="deactivate-account-confirm-button"
            label="Yes, deactivate my account"
            onPress={handleDeactivate}
            loading={submitting}
          />
        </>
      )}

      <Text className="mb-2 mt-8 text-sm text-text-tertiary">
        Already deactivated and changed your mind? Signing back in still works during the 30-day
        window — use that, then reactivate here.
      </Text>
      <Button
        testID="reactivate-account-button"
        label="Reactivate my account"
        onPress={handleCancelDeactivation}
        loading={submitting}
        variant="secondary"
      />
    </Screen>
  );
}
