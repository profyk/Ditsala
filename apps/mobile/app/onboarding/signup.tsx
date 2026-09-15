import { useRouter } from "expo-router";
import { useState } from "react";
import { Text } from "react-native";

import { Button } from "../../components/Button";
import { Screen } from "../../components/Screen";
import { TextField } from "../../components/TextField";
import { ApiError, onboardingApi } from "../../lib/api";
import { useOnboarding } from "../../lib/onboarding-context";
import { isValidDateOfBirth, isValidEmail, isValidPhone } from "../../lib/validation";

export default function Signup() {
  const router = useRouter();
  const { setSession } = useOnboarding();

  const [displayName, setDisplayName] = useState("");
  const [dateOfBirth, setDateOfBirth] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [nationalId, setNationalId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const canSubmit =
    displayName.trim().length > 0 &&
    isValidDateOfBirth(dateOfBirth) &&
    isValidEmail(email) &&
    isValidPhone(phone) &&
    nationalId.trim().length >= 4;

  async function handleSubmit() {
    setError(null);
    setSubmitting(true);
    try {
      const session = await onboardingApi.signup({
        display_name: displayName.trim(),
        date_of_birth: dateOfBirth,
        email: email.trim(),
        phone: phone.trim(),
        national_id: nationalId.trim(),
      });
      setSession(session.onboarding_token, session.account_state);
      router.push("/onboarding/verify-email");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create your account.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Screen>
      <Text className="mb-2 mt-8 text-3xl font-semibold text-text-primary">Create your account</Text>
      <Text className="mb-8 text-base text-text-secondary">
        DITSALA verifies every member’s identity before they can join a Circle.
      </Text>

      <TextField
        label="Full name"
        value={displayName}
        onChangeText={setDisplayName}
        autoCapitalize="words"
        testID="display-name-input"
      />
      <TextField
        label="Date of birth (YYYY-MM-DD)"
        value={dateOfBirth}
        onChangeText={setDateOfBirth}
        placeholder="1990-01-01"
        keyboardType="numbers-and-punctuation"
        testID="date-of-birth-input"
      />
      <TextField
        label="Email"
        value={email}
        onChangeText={setEmail}
        autoCapitalize="none"
        keyboardType="email-address"
        testID="email-input"
      />
      <TextField
        label="Phone number"
        value={phone}
        onChangeText={setPhone}
        placeholder="+27 82 123 4567"
        keyboardType="phone-pad"
        testID="phone-input"
      />
      <TextField
        label="National ID number"
        value={nationalId}
        onChangeText={setNationalId}
        testID="national-id-input"
      />

      {error ? <Text className="mb-4 text-sm text-danger">{error}</Text> : null}

      <Button
        testID="signup-submit-button"
        label="Continue"
        onPress={handleSubmit}
        loading={submitting}
        disabled={!canSubmit}
      />
    </Screen>
  );
}
