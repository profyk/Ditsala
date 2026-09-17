/**
 * Colors mirror packages/ui-tokens/src/colors.ts (dark palette) exactly.
 * Duplicated rather than imported: tailwind.config.js runs under plain
 * Node/CommonJS, and ui-tokens ships raw TypeScript with no build step
 * (by design — it's consumed directly by TS-aware bundlers elsewhere).
 * Keep these in sync by hand until ui-tokens gets a compiled JS output.
 */
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{js,jsx,ts,tsx}", "./components/**/*.{js,jsx,ts,tsx}"],
  presets: [require("nativewind/preset")],
  theme: {
    extend: {
      colors: {
        background: "#0B0B12",
        surface: "#15151F",
        "surface-raised": "#1D1D2A",
        border: "#2A2A3A",
        "border-strong": "#3D3D52",
        "text-primary": "#F6F6F9",
        "text-secondary": "#A3A3B5",
        "text-tertiary": "#6E6E85",
        accent: "#7C6AFF",
        "accent-pressed": "#6453E8",
        "accent-muted": "#241F45",
        success: "#2FD999",
        warning: "#F5A623",
        danger: "#FF5A5F",
        info: "#4FA8FF",
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
