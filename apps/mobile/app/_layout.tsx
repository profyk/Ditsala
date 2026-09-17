import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";

// Must load before anything in lib/crypto runs — it's what makes
// `nacl.randomBytes` a real CSPRNG on React Native (see
// docs/adr/0013-nacl-e2ee-instead-of-libsignal.md). Order matters: this
// import has to come before "../global.css" resolves any crypto usage
// transitively, so it stays first in the file.
import "react-native-get-random-values";
import "../global.css";
import { CallProvider } from "../lib/call-context";
import { OnboardingProvider } from "../lib/onboarding-context";
import { RecoveryProvider } from "../lib/recovery-context";

export default function RootLayout() {
  return (
    <OnboardingProvider>
      <RecoveryProvider>
        <CallProvider>
          <StatusBar style="light" />
          <Stack
            screenOptions={{
              headerShown: false,
              contentStyle: { backgroundColor: "#0B0B12" },
            }}
          />
        </CallProvider>
      </RecoveryProvider>
    </OnboardingProvider>
  );
}
