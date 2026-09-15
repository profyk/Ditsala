import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";

import "../global.css";
import { OnboardingProvider } from "../lib/onboarding-context";

export default function RootLayout() {
  return (
    <OnboardingProvider>
      <StatusBar style="light" />
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: "#0A0A0B" },
        }}
      />
    </OnboardingProvider>
  );
}
