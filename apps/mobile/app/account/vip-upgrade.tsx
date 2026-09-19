import { useRouter } from "expo-router";
import { useState } from "react";
import { Linking, Text } from "react-native";

import { Button } from "../../components/Button";
import { Screen } from "../../components/Screen";
import { TextField } from "../../components/TextField";
import { billingApi } from "../../lib/billing-api";
import { ApiError } from "../../lib/api";
import { getAccessToken } from "../../lib/session";

/**
 * Real "Upgrade to VIP" flow (ADR 0012) — no dev shortcut, no bypass. The
 * backend already ignores whatever fields a phone-only account has on
 * file (VipUpgradeStartRequest's docstring), so this form just offers
 * them; submitting hands off to Stitch's real checkout.
 */
export default function VipUpgrade() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [dateOfBirth, setDateOfBirth] = useState("");
  const [nationalId, setNationalId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleContinue() {
    setError(null);
    setSubmitting(true);
    try {
      const accessToken = await getAccessToken();
      if (!accessToken) {
        router.replace("/");
        return;
      }
      const initiation = await billingApi.startUpgrade(accessToken, {
        email: email.trim() || null,
        date_of_birth: dateOfBirth.trim() || null,
        national_id: nationalId.trim() || null,
      });
      await Linking.openURL(initiation.payment_url);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start the upgrade.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Screen>
      <Text className="mb-2 mt-8 text-3xl font-semibold text-text-primary">Upgrade to VIP</Text>
      <Text className="mb-8 text-base leading-6 text-text-secondary">
        VIP adds two-factor login, Emergency SOS, and identity verification. Fill in anything
        below that isn&apos;t already on your account, then continue to payment.
      </Text>

      <TextField
        label="Email"
        value={email}
        onChangeText={setEmail}
        placeholder="you@example.com"
        keyboardType="email-address"
        autoCapitalize="none"
        testID="vip-upgrade-email-input"
      />
      <TextField
        label="Date of birth"
        value={dateOfBirth}
        onChangeText={setDateOfBirth}
        placeholder="YYYY-MM-DD"
        testID="vip-upgrade-dob-input"
      />
      <TextField
        label="National ID"
        value={nationalId}
        onChangeText={setNationalId}
        placeholder="Optional"
        testID="vip-upgrade-national-id-input"
      />

      {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}

      <Button
        testID="vip-upgrade-continue-button"
        label="Continue to payment"
        onPress={handleContinue}
        loading={submitting}
      />
    </Screen>
  );
}
