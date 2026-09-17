import { dark } from "@ditsala/ui-tokens";
import { Text, TextInput, View, type TextInputProps } from "react-native";

import { Icon, type IconName } from "./Icon";

interface TextFieldProps extends TextInputProps {
  label: string;
  error?: string;
  icon?: IconName;
}

/** v2 — 12px radius (was a flat, sharp `rounded`), an optional leading
 * icon, and a wrapped input so the icon can sit inline without
 * disturbing `TextInput`'s own padding/hit box. */
export function TextField({ label, error, icon, className = "", ...inputProps }: TextFieldProps) {
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
            <Icon name={icon} size={18} color={dark.textTertiary} />
          </View>
        ) : null}
        <TextInput
          className={["flex-1 py-3 text-base text-text-primary", className].join(" ")}
          placeholderTextColor={dark.textTertiary}
          {...inputProps}
        />
      </View>
      {error ? <Text className="mt-1 text-sm text-danger">{error}</Text> : null}
    </View>
  );
}
