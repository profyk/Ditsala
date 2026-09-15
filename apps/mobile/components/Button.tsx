import { dark } from "@ditsala/ui-tokens";
import { ActivityIndicator, Pressable, Text } from "react-native";

interface ButtonProps {
  label: string;
  onPress: () => void;
  variant?: "primary" | "secondary";
  loading?: boolean;
  disabled?: boolean;
  testID?: string;
}

/**
 * Gold accent reserved for the primary call-to-action (docs/DITSALA_MASTER_SPEC.md
 * brand: "single accent color reserved for calls-to-action"). No rounded-pill
 * chrome — restrained, small radius, matches ui-tokens `radius.md`.
 */
export function Button({
  label,
  onPress,
  variant = "primary",
  loading = false,
  disabled = false,
  testID,
}: ButtonProps) {
  const isPrimary = variant === "primary";
  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      disabled={disabled || loading}
      className={[
        "items-center justify-center rounded py-4 px-6",
        isPrimary ? "bg-accent active:bg-accent-pressed" : "bg-surface-raised active:bg-border",
        disabled || loading ? "opacity-50" : "",
      ].join(" ")}
    >
      {loading ? (
        <ActivityIndicator color={isPrimary ? dark.background : dark.textPrimary} />
      ) : (
        <Text
          className={[
            "text-base font-semibold",
            isPrimary ? "text-background" : "text-text-primary",
          ].join(" ")}
        >
          {label}
        </Text>
      )}
    </Pressable>
  );
}
