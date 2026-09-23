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
import { ThemeProvider, useTheme } from "../lib/theme-context";

function RootStack() {
  const { theme, colors } = useTheme();
  return (
    <>
      <StatusBar style={theme === "dark" ? "light" : "dark"} />
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: colors.background },
        }}
      />
    </>
  );
}

export default function RootLayout() {
  return (
    <ThemeProvider>
      <OnboardingProvider>
        <RecoveryProvider>
          <CallProvider>
            <RootStack />
          </CallProvider>
        </RecoveryProvider>
      </OnboardingProvider>
    </ThemeProvider>
  );
}
