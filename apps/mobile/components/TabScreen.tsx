import type { PropsWithChildren } from "react";
import { ScrollView } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { TabBar } from "./TabBar";

/** Screen wrapper for the four tab-bar destinations (home, messages,
 * circle, settings) — like Screen, but reserves the bottom edge for
 * TabBar instead of applying it to the scroll content, and TabBar
 * handles its own bottom safe-area inset. */
export function TabScreen({ children }: PropsWithChildren) {
  return (
    <SafeAreaView className="flex-1 bg-background" edges={["top"]}>
      <ScrollView className="flex-1 px-6" contentContainerStyle={{ flexGrow: 1 }}>
        {children}
      </ScrollView>
      <TabBar />
    </SafeAreaView>
  );
}
