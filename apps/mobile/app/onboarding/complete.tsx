import { Text, View } from "react-native";

import { Screen } from "../../components/Screen";
import { useOnboarding } from "../../lib/onboarding-context";

/**
 * Holding screen — device registration and Signal key generation (Phase 3)
 * is what actually completes onboarding into `active`. Nothing to submit
 * here yet; this screen exists so the flow has a coherent endpoint until
 * Phase 3 wires in the real device-activation step.
 */
export default function Complete() {
  const { accountState } = useOnboarding();

  return (
    <Screen scroll={false}>
      <View className="flex-1 items-center justify-center">
        <Text className="mb-3 text-3xl font-semibold text-text-primary">You’re almost there</Text>
        <Text className="text-center text-base text-text-secondary">
          Your identity is verified. Setting up your device finishes in a moment.
        </Text>
        <Text className="mt-6 text-xs text-text-tertiary">Status: {accountState}</Text>
      </View>
    </Screen>
  );
}
