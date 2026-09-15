import type { PropsWithChildren } from "react";
import { ScrollView } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

interface ScreenProps extends PropsWithChildren {
  scroll?: boolean;
}

/** Dark-first canvas every onboarding screen sits on — see ui-tokens `dark.background`. */
export function Screen({ children, scroll = true }: ScreenProps) {
  const content = (
    <SafeAreaView className="flex-1 bg-background px-6" edges={["top", "bottom"]}>
      {children}
    </SafeAreaView>
  );

  if (!scroll) return content;

  return (
    <SafeAreaView className="flex-1 bg-background" edges={["top", "bottom"]}>
      <ScrollView
        className="flex-1 px-6"
        contentContainerStyle={{ flexGrow: 1 }}
        keyboardShouldPersistTaps="handled"
      >
        {children}
      </ScrollView>
    </SafeAreaView>
  );
}
