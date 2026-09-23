import { useState } from "react";
import { FlatList, Modal, Pressable, Text, TextInput, View } from "react-native";

import { COUNTRIES, type Country } from "../lib/countries";
import { useTheme, useThemeVars } from "../lib/theme-context";

interface CountryCodePickerProps {
  value: Country;
  onChange: (country: Country) => void;
  testID?: string;
}

/** A dependency-free country/dial-code picker — a button that opens a
 * searchable modal list, matching this project's pattern of avoiding new
 * native modules where React Native primitives suffice (see ADR 0013's
 * `quick-crypto` deferral for the same reasoning). */
export function CountryCodePicker({ value, onChange, testID }: CountryCodePickerProps) {
  const { colors } = useTheme();
  // Re-applies the theme's CSS vars inside the Modal's own native root —
  // see useThemeVars's docstring (lib/theme-context.tsx) for why a Modal
  // needs this even though it's nested under ThemeProvider in the React
  // tree; without it every bg-*/text-* className below resolves to
  // nothing, same bug ScheduleDateTimePicker's calendar modal had.
  const themeVars = useThemeVars();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const filtered = COUNTRIES.filter((country) => {
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return (
      country.name.toLowerCase().includes(q) ||
      country.dialCode.includes(q) ||
      country.iso2.toLowerCase() === q
    );
  });

  return (
    <>
      <Pressable
        testID={testID}
        onPress={() => setOpen(true)}
        className="mr-2 flex-row items-center rounded-xl border border-border bg-surface px-3 py-3"
      >
        <Text className="text-base text-text-primary">
          {value.flag} {value.dialCode}
        </Text>
      </Pressable>

      <Modal visible={open} animationType="slide" onRequestClose={() => setOpen(false)}>
        <View style={themeVars} className="flex-1 bg-background px-6 pt-16">
          <Text className="mb-4 text-2xl font-semibold text-text-primary">Choose a country</Text>
          <TextInput
            testID="country-search-input"
            value={query}
            onChangeText={setQuery}
            placeholder="Search by country or code"
            placeholderTextColor={colors.textTertiary}
            autoCapitalize="none"
            className="mb-4 rounded-xl border border-border bg-surface px-4 py-3 text-base text-text-primary"
          />
          <FlatList
            data={filtered}
            keyExtractor={(item) => item.iso2}
            renderItem={({ item }) => (
              <Pressable
                testID={`country-option-${item.iso2}`}
                onPress={() => {
                  onChange(item);
                  setQuery("");
                  setOpen(false);
                }}
                className="flex-row items-center justify-between border-b border-border py-4"
              >
                <Text className="text-base text-text-primary">
                  {item.flag} {item.name}
                </Text>
                <Text className="text-base text-text-secondary">{item.dialCode}</Text>
              </Pressable>
            )}
          />
          <Pressable className="items-center py-4" onPress={() => setOpen(false)}>
            <Text className="text-sm font-medium text-accent">Cancel</Text>
          </Pressable>
        </View>
      </Modal>
    </>
  );
}
