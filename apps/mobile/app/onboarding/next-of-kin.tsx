import { useRouter } from "expo-router";
import { useState } from "react";
import { Text } from "react-native";

import { Button } from "../../components/Button";
import { Screen } from "../../components/Screen";
import { TextField } from "../../components/TextField";
import { ApiError, onboardingApi } from "../../lib/api";
import { useOnboarding } from "../../lib/onboarding-context";

export default function NextOfKin() {
  const router = useRouter();
  const { token, setAccountState } = useOnboarding();
  const [fullName, setFullName] = useState("");
  const [relationship, setRelationship] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const canSubmit =
    fullName.trim().length > 0 && relationship.trim().length > 0 && phone.trim().length >= 8;

  async function handleSubmit() {
    if (!token) return;
    setError(null);
    setSubmitting(true);
    try {
      const result = await onboardingApi.addNextOfKin(token, {
        full_name: fullName.trim(),
        relationship: relationship.trim(),
        phone: phone.trim(),
        email: email.trim() || null,
      });
      setAccountState(result.account_state);
      router.push("/onboarding/set-code");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save your next of kin.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Screen>
      <Text className="mb-2 mt-8 text-3xl font-semibold text-text-primary">Next of kin</Text>
      <Text className="mb-8 text-base text-text-secondary">
        Used only to notify someone you trust if you ever trigger an SOS — never shared,
        sold, or used for marketing.
      </Text>

      <TextField
        label="Full name"
        value={fullName}
        onChangeText={setFullName}
        autoCapitalize="words"
        testID="next-of-kin-name-input"
      />
      <TextField
        label="Relationship"
        value={relationship}
        onChangeText={setRelationship}
        placeholder="Sister, parent, friend…"
        testID="next-of-kin-relationship-input"
      />
      <TextField
        label="Phone number"
        value={phone}
        onChangeText={setPhone}
        keyboardType="phone-pad"
        testID="next-of-kin-phone-input"
      />
      <TextField
        label="Email (optional)"
        value={email}
        onChangeText={setEmail}
        autoCapitalize="none"
        keyboardType="email-address"
        testID="next-of-kin-email-input"
      />

      {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}

      <Button
        testID="next-of-kin-submit-button"
        label="Continue"
        onPress={handleSubmit}
        loading={submitting}
        disabled={!canSubmit}
      />
    </Screen>
  );
}
