import { useState } from "react";
import { Pressable, Text, TextInput, View, type TextInputProps } from "react-native";

import { Icon, type IconName } from "./Icon";
import { useTheme } from "../lib/theme-context";

interface TextFieldProps extends TextInputProps {
  label: string;
  error?: string;
  icon?: IconName;
}

/** v2 — 12px radius (was a flat, sharp `rounded`), an optional leading
 * icon, and a wrapped input so the icon can sit inline without
 * disturbing `TextInput`'s own padding/hit box. Passing `secureTextEntry`
 * also renders a trailing Show/Hide toggle (a text button, not an icon —
 * this app's hand-built `Icon` set has no eye glyph, and adding one just
 * for this wasn't worth a new geometric primitive) so a meeting password
 * or the DITSALA Code can be visually double-checked before submitting,
 * same as any password field a user might mistype without ever noticing. */
export function TextField({
  label,
  error,
  icon,
  className = "",
  secureTextEntry,
  ...inputProps
}: TextFieldProps) {
  const { colors } = useTheme();
  const [revealed, setRevealed] = useState(false);
  const isPasswordField = secureTextEntry !== undefined;

  return (
    <View className="mb-5">
      <Text className="mb-2 text-sm font-medium text-text-secondary">{label}</Text>
      <View
        className={[
          "flex-row items-center rounded-xl border bg-surface px-4",
          error ? "border-danger" : "border-border",
        ].join(" ")}
      >
        {icon ? (
          <View style={{ marginRight: 10 }}>
            <Icon name={icon} size={18} color={colors.textTertiary} />
          </View>
        ) : null}
        <TextInput
          className={["flex-1 py-3 text-base text-text-primary", className].join(" ")}
          placeholderTextColor={colors.textTertiary}
          secureTextEntry={isPasswordField ? secureTextEntry && !revealed : secureTextEntry}
          {...inputProps}
        />
        {isPasswordField ? (
          <Pressable
            onPress={() => setRevealed((v) => !v)}
            hitSlop={8}
            style={{ marginLeft: 8, paddingVertical: 4 }}
          >
            <Text className="text-xs font-medium text-accent">
              {revealed ? "Hide" : "Show"}
            </Text>
          </Pressable>
        ) : null}
      </View>
      {error ? <Text className="mt-1 text-sm text-danger">{error}</Text> : null}
    </View>
  );
}
