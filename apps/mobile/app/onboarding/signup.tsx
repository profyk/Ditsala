import { dark } from "@ditsala/ui-tokens";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";

import { Button } from "../../components/Button";
import { CountryCodePicker } from "../../components/CountryCodePicker";
import { Screen } from "../../components/Screen";
import { TextField } from "../../components/TextField";
import { ApiError, onboardingApi } from "../../lib/api";
import { DEFAULT_COUNTRY, toE164, type Country } from "../../lib/countries";
import { useOnboarding } from "../../lib/onboarding-context";

/**
 * ADR 0014 — the entire normal-tier signup: display name + a phone number
 * with its country code. No email, no date of birth, no national ID, no
 * KYC — those only apply to a paid VIP upgrade later, never at signup.
 */
export default function Signup() {
  const router = useRouter();
  const { setSession } = useOnboarding();

  const [displayName, setDisplayName] = useState("");
  const [country, setCountry] = useState<Country>(DEFAULT_COUNTRY);
  const [localNumber, setLocalNumber] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const digitsOnly = localNumber.replace(/\D/g, "");
  const canSubmit = displayName.trim().length > 0 && digitsOnly.length >= 6 && digitsOnly.length <= 15;

  async function handleSubmit() {
    setError(null);
    setSubmitting(true);
    try {
      const session = await onboardingApi.signupPhone({
        display_name: displayName.trim(),
        phone: toE164(country, localNumber),
      });
      setSession(session.onboarding_token, session.account_state, "pin");
      router.push("/onboarding/verify-phone");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create your account.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Screen>
      <Text className="mb-2 mt-8 text-3xl font-semibold text-text-primary">Create your account</Text>
      <Text className="mb-8 text-base leading-6 text-text-secondary">
        Just your name and phone number — free to join. Upgrade to VIP any time for a verified
        badge and a trusted, private space to speak with other VIP members.
      </Text>

      <TextField
        label="Full name"
        value={displayName}
        onChangeText={setDisplayName}
        autoCapitalize="words"
        testID="display-name-input"
      />

      <View className="mb-5">
        <Text className="mb-2 text-sm font-medium text-text-secondary">Phone number</Text>
        <View className="flex-row items-center">
          <CountryCodePicker value={country} onChange={setCountry} testID="country-code-picker" />
          <TextInput
            value={localNumber}
            onChangeText={setLocalNumber}
            placeholder="82 123 4567"
            placeholderTextColor={dark.textTertiary}
            keyboardType="number-pad"
            testID="phone-input"
            className="flex-1 rounded border border-border bg-surface px-4 py-3 text-base text-text-primary"
          />
        </View>
      </View>

      {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}

      <Button
        testID="signup-submit-button"
        label="Continue"
        onPress={handleSubmit}
        loading={submitting}
        disabled={!canSubmit}
      />
      <Pressable className="mt-5 items-center py-2" onPress={() => router.push("/login")}>
        <Text className="text-sm font-medium text-accent">
          Already have an account? Sign in
        </Text>
      </Pressable>
    </Screen>
  );
}
