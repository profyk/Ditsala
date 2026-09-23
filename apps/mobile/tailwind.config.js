/**
 * Colors are CSS custom properties, not literals — lib/theme.ts's
 * ThemeProvider sets them via NativeWind's `vars()` on a root View,
 * switching between packages/ui-tokens/src/colors.ts's dark and light
 * palettes at runtime. Every existing `className="bg-surface ..."` etc.
 * across the app keeps working unchanged and just becomes theme-reactive
 * automatically; only direct `dark.X` imports (inline `style`/`color`
 * props that can't take a className) needed updating to the `useTheme()`
 * hook instead.
 */
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{js,jsx,ts,tsx}", "./components/**/*.{js,jsx,ts,tsx}"],
  presets: [require("nativewind/preset")],
  theme: {
    extend: {
      colors: {
        background: "var(--color-background)",
        surface: "var(--color-surface)",
        "surface-raised": "var(--color-surface-raised)",
        border: "var(--color-border)",
        "border-strong": "var(--color-border-strong)",
        "text-primary": "var(--color-text-primary)",
        "text-secondary": "var(--color-text-secondary)",
        "text-tertiary": "var(--color-text-tertiary)",
        accent: "var(--color-accent)",
        "accent-pressed": "var(--color-accent-pressed)",
        "accent-muted": "var(--color-accent-muted)",
        success: "var(--color-success)",
        warning: "var(--color-warning)",
        danger: "var(--color-danger)",
        info: "var(--color-info)",
      },
      borderRadius: {
        xs: "4px",
        sm: "8px",
        md: "12px",
        lg: "16px",
        xl: "24px",
      },
    },
  },
  plugins: [],
};
