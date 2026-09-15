import { dark } from "@ditsala/ui-tokens";
import { Text, TextInput, View, type TextInputProps } from "react-native";

interface TextFieldProps extends TextInputProps {
  label: string;
  error?: string;
}

export function TextField({ label, error, ...inputProps }: TextFieldProps) {
  return (
    <View className="mb-5">
      <Text className="mb-2 text-sm font-medium text-text-secondary">{label}</Text>
      <TextInput
        className={[
          "rounded border bg-surface px-4 py-3 text-base text-text-primary",
          error ? "border-danger" : "border-border",
        ].join(" ")}
        placeholderTextColor={dark.textTertiary}
        {...inputProps}
      />
      {error ? <Text className="mt-1 text-sm text-danger">{error}</Text> : null}
    </View>
  );
}
