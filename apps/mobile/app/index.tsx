import { useRouter } from "expo-router";
import { Text, View } from "react-native";

import { Button } from "../components/Button";
import { Screen } from "../components/Screen";

export default function Welcome() {
  const router = useRouter();

  return (
    <Screen scroll={false}>
      <View className="flex-1 items-center justify-center">
        <Text className="text-5xl font-semibold tracking-wide text-text-primary">DITSALA</Text>
        <Text className="mt-3 text-lg text-text-primary">Speak with Confidence.</Text>
        <Text className="mt-1 text-base text-text-secondary">Your trusted circle.</Text>
      </View>
      <View className="mb-8">
        <Button
          testID="get-started-button"
          label="Get Started"
          onPress={() => router.push("/onboarding/signup")}
        />
      </View>
    </Screen>
  );
}
