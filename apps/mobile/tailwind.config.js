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
        background: "#0A0A0B",
        surface: "#141518",
        "surface-raised": "#1C1E22",
        border: "#2A2C31",
        "border-strong": "#3A3D44",
        "text-primary": "#F5F5F2",
        "text-secondary": "#9B9EA6",
        "text-tertiary": "#6B6E76",
        accent: "#C8A059",
        "accent-pressed": "#B08B47",
        "accent-muted": "#3A3222",
        success: "#4C9A8E",
        warning: "#D9A441",
        danger: "#C1493A",
        info: "#5B8AA6",
      },
    },
  },
  plugins: [],
};
