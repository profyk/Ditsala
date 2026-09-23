import { ActivityIndicator, Pressable, Text, View } from "react-native";

import { Icon, type IconName } from "./Icon";
import { useTheme } from "../lib/theme-context";

interface ButtonProps {
  label: string;
  onPress: () => void;
  variant?: "primary" | "secondary" | "danger" | "ghost";
  size?: "md" | "lg";
  loading?: boolean;
  disabled?: boolean;
  icon?: IconName;
  testID?: string;
}

const VARIANT_STYLE: Record<
  NonNullable<ButtonProps["variant"]>,
  { bg: string; text: string; border?: string; shadow?: boolean }
> = {
  primary: { bg: "bg-accent active:bg-accent-pressed", text: "text-white", shadow: true },
  secondary: {
    bg: "bg-surface-raised active:bg-border",
    text: "text-text-primary",
    border: "border border-border",
  },
  danger: { bg: "bg-danger active:opacity-90", text: "text-white", shadow: true },
  ghost: { bg: "bg-transparent active:bg-surface-raised", text: "text-accent" },
};

/**
 * v2 — a real 16px radius and a soft elevation on the filled variants
 * (primary/danger) instead of the old flat, sharp-cornered look, plus an
 * optional leading icon. `ghost` is new: a borderless, text-only variant
 * for low-emphasis actions (e.g. "Skip", inline row actions) that
 * `secondary`'s visible card chrome was too heavy for.
 */
export function Button({
  label,
  onPress,
  variant = "primary",
  size = "lg",
  loading = false,
  disabled = false,
  icon,
  testID,
}: ButtonProps) {
  const { colors } = useTheme();
  const style = VARIANT_STYLE[variant];
  const padding = size === "lg" ? "py-4 px-6" : "py-3 px-5";

  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      disabled={disabled || loading}
      style={
        style.shadow && !disabled && !loading
          ? {
              shadowColor: colors.accent,
              shadowOpacity: 0.35,
              shadowRadius: 12,
              shadowOffset: { width: 0, height: 6 },
              elevation: 4,
            }
          : undefined
      }
      className={[
        "flex-row items-center justify-center gap-2 rounded-xl",
        padding,
        style.bg,
        style.border ?? "",
        disabled || loading ? "opacity-50" : "",
      ].join(" ")}
    >
      {loading ? (
        <ActivityIndicator color={variant === "secondary" || variant === "ghost" ? colors.textPrimary : "#FFFFFF"} />
      ) : (
        <>
          {icon ? (
            <View>
              <Icon
                name={icon}
                size={18}
                color={variant === "secondary" || variant === "ghost" ? colors.textPrimary : "#FFFFFF"}
              />
            </View>
          ) : null}
          <Text className={["text-base font-semibold", style.text].join(" ")}>{label}</Text>
        </>
      )}
    </Pressable>
  );
}
