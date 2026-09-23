import { Stack } from "expo-router";

import { useTheme } from "../../lib/theme-context";

export default function MeetLayout() {
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
