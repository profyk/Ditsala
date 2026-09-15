import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";

import "../global.css";
import { CallProvider } from "../lib/call-context";
import { OnboardingProvider } from "../lib/onboarding-context";

export default function RootLayout() {
  return (
    <OnboardingProvider>
      <CallProvider>
        <StatusBar style="light" />
        <Stack
          screenOptions={{
            headerShown: false,
            contentStyle: { backgroundColor: "#0A0A0B" },
          }}
        />
      </CallProvider>
    </OnboardingProvider>
  );
}
