import { Stack } from "expo-router";

export default function CallsLayout() {
  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: "#0B0B12" },
        gestureEnabled: false,
      }}
    />
  );
}
