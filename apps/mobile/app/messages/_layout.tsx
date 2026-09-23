import { Stack } from "expo-router";

import { useTheme } from "../../lib/theme-context";

export default function MessagesLayout() {
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
