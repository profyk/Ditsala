import { Stack } from "expo-router";

import { useTheme } from "../../lib/theme-context";

export default function SosLayout() {
  const { colors } = useTheme();
  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: colors.background },
      }}
    />
  );
}
