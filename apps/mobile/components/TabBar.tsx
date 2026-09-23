import { usePathname, useRouter } from "expo-router";
import { Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Icon, type IconName } from "./Icon";
import { useTheme } from "../lib/theme-context";

const TABS: { path: string; label: string; icon: IconName; testID: string }[] = [
  { path: "/home", label: "Home", icon: "home", testID: "tab-home" },
  { path: "/messages", label: "Messages", icon: "messages", testID: "tab-messages" },
  { path: "/circle", label: "Circle", icon: "circle", testID: "tab-circle" },
  { path: "/settings", label: "Settings", icon: "settings", testID: "tab-settings" },
];

/**
 * A persistent bottom tab bar included directly in the four primary
 * screens (not an expo-router `(tabs)` group) — this app has no typed
 * routes, so a full route-tree restructuring risked silently breaking
 * one of the many existing `router.push("/...")` call sites across 30+
 * screens with no compiler safety net to catch it. This gets the same
 * "feels like a normal app" persistent nav without touching a single
 * existing route path. Switching tabs uses `replace`, not `push` — the
 * four tabs are peers, not a drill-down stack, so tapping between them
 * shouldn't grow the back stack.
 */
export function TabBar() {
  const pathname = usePathname();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors } = useTheme();

  return (
    <View
      style={{ paddingBottom: Math.max(insets.bottom, 10) }}
      className="flex-row border-t border-border bg-surface"
    >
      {TABS.map((tab) => {
        const active = pathname === tab.path || pathname.startsWith(`${tab.path}/`);
        return (
          <Pressable
            key={tab.path}
            testID={tab.testID}
            onPress={() => {
              if (!active) router.replace(tab.path);
            }}
            className="flex-1 items-center gap-1 pt-2.5"
          >
            <Icon name={tab.icon} size={22} color={active ? colors.accent : colors.textTertiary} strokeWidth={2.2} />
            <Text
              className={["text-xs font-medium", active ? "text-accent" : "text-text-tertiary"].join(" ")}
            >
              {tab.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}
