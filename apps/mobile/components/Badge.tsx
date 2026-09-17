import { Text, View } from "react-native";

type Tone = "neutral" | "info" | "accent" | "success" | "warning" | "danger";

const TONE_CLASSES: Record<Tone, string> = {
  neutral: "bg-surface-raised",
  info: "bg-info/15",
  accent: "bg-accent-muted",
  success: "bg-success/15",
  warning: "bg-warning/15",
  danger: "bg-danger/15",
};

const TONE_TEXT_CLASSES: Record<Tone, string> = {
  neutral: "text-text-secondary",
  info: "text-info",
  accent: "text-accent",
  success: "text-success",
  warning: "text-warning",
  danger: "text-danger",
};

export function Badge({ label, tone = "neutral" }: { label: string; tone?: Tone }) {
  return (
    <View className={["rounded-full px-2.5 py-1", TONE_CLASSES[tone]].join(" ")}>
      <Text className={["text-xs font-semibold", TONE_TEXT_CLASSES[tone]].join(" ")}>{label}</Text>
    </View>
  );
}
