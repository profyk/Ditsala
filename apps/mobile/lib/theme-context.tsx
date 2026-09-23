import { dark, light, type ColorPalette } from "@ditsala/ui-tokens";
import * as SecureStore from "expo-secure-store";
import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { useColorScheme as useSystemColorScheme, View } from "react-native";
import { vars } from "nativewind";

/**
 * Light/dark mode — an explicit user choice persisted via expo-secure-store
 * (reused for a non-secret preference rather than adding a new dependency
 * like @react-native-async-storage, matching this app's existing
 * "avoid a new native dependency where an installed one already does the
 * job" convention), falling back to the OS scheme when nothing's been
 * chosen yet. Dark stays the default look (brand's "dark-first" decision)
 * whenever the OS itself reports no preference either.
 *
 * Every existing `className="bg-surface ..."` Tailwind utility across the
 * app becomes theme-reactive for free, via NativeWind's `vars()` CSS
 * custom properties (see tailwind.config.js) applied on the wrapping
 * <View> this provider renders — no per-screen className changes needed.
 * Only direct `dark.X` imports from ui-tokens (inline style/color props
 * that can't take a className, e.g. an <Icon color={...}>) need the
 * `colors` this hook returns instead.
 */

export type Theme = "dark" | "light";

const STORAGE_KEY = "ditsala-theme";

const THEME_VARS: Record<Theme, ReturnType<typeof vars>> = {
  dark: vars({
    "--color-background": dark.background,
    "--color-surface": dark.surface,
    "--color-surface-raised": dark.surfaceRaised,
    "--color-border": dark.border,
    "--color-border-strong": dark.borderStrong,
    "--color-text-primary": dark.textPrimary,
    "--color-text-secondary": dark.textSecondary,
    "--color-text-tertiary": dark.textTertiary,
    "--color-accent": dark.accent,
    "--color-accent-pressed": dark.accentPressed,
    "--color-accent-muted": dark.accentMuted,
    "--color-success": dark.success,
    "--color-warning": dark.warning,
    "--color-danger": dark.danger,
    "--color-info": dark.info,
  }),
  light: vars({
    "--color-background": light.background,
    "--color-surface": light.surface,
    "--color-surface-raised": light.surfaceRaised,
    "--color-border": light.border,
    "--color-border-strong": light.borderStrong,
    "--color-text-primary": light.textPrimary,
    "--color-text-secondary": light.textSecondary,
    "--color-text-tertiary": light.textTertiary,
    "--color-accent": light.accent,
    "--color-accent-pressed": light.accentPressed,
    "--color-accent-muted": light.accentMuted,
    "--color-success": light.success,
    "--color-warning": light.warning,
    "--color-danger": light.danger,
    "--color-info": light.info,
  }),
};

const PALETTES: Record<Theme, ColorPalette> = { dark, light };

interface ThemeContextValue {
  theme: Theme;
  colors: ColorPalette;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const systemScheme = useSystemColorScheme();
  const [theme, setThemeState] = useState<Theme>("dark");

  useEffect(() => {
    let cancelled = false;
    SecureStore.getItemAsync(STORAGE_KEY)
      .then((stored) => {
        if (cancelled) return;
        if (stored === "light" || stored === "dark") {
          setThemeState(stored);
        } else if (systemScheme === "light") {
          setThemeState("light");
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
    // Only re-resolve from storage/system once on mount — after that,
    // setTheme() below is the sole source of truth so a user's explicit
    // choice never gets silently overridden by an OS scheme change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function setTheme(next: Theme) {
    setThemeState(next);
    SecureStore.setItemAsync(STORAGE_KEY, next).catch(() => undefined);
  }

  function toggleTheme() {
    setTheme(theme === "dark" ? "light" : "dark");
  }

  const value = useMemo<ThemeContextValue>(
    () => ({ theme, colors: PALETTES[theme], setTheme, toggleTheme }),
    [theme]
  );

  return (
    <ThemeContext.Provider value={value}>
      <View style={[{ flex: 1 }, THEME_VARS[theme]]}>{children}</View>
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within a ThemeProvider");
  return ctx;
}

/**
 * The same `vars()` style `ThemeProvider` applies on its wrapping <View> —
 * for re-applying inside a React Native `<Modal>`.
 *
 * `<Modal>` renders its children into a separate native root (a new
 * window on iOS, a new Dialog on Android): NativeWind's `vars()` sets CSS
 * custom properties via an inline `style` prop, and that style only
 * cascades through the *native* view tree it's attached to — a `<Modal>`
 * child is not a native descendant of `ThemeProvider`'s `<View>` even
 * though it's still a React-tree descendant. The result: every
 * `className="bg-surface"`/`"text-text-primary"`/etc. *inside* a Modal
 * resolves each `var(--color-*)` to nothing, rendering transparent with
 * default text color — the modal's own content becomes unreadable against
 * whatever's behind it. Every `<Modal>` in this app needs to spread this
 * hook's return value onto its own outermost View (see
 * `ScheduleDateTimePicker`/`CountryCodePicker` for the pattern) — a real,
 * previously-shipped bug, not a hypothetical one.
 */
export function useThemeVars(): ReturnType<typeof vars> {
  const { theme } = useTheme();
  return THEME_VARS[theme];
}
