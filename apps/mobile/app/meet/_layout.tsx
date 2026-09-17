import { Stack } from "expo-router";

export default function MeetLayout() {
  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: "#0B0B12" },
      }}
    />
  );
}
