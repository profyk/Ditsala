/**
 * Ditsala palette v2 — a modern, premium messaging-app identity: dark-
 * first, confident single-accent system. Replaces the earlier gold
 * "private-members'-club" direction (kept in git history, not here) per
 * an explicit full-visual-identity redesign. Indigo-violet as the one
 * brand/CTA accent (distinct from WhatsApp green / Telegram-Signal blue
 * / iMessage blue), emerald reserved for verified/success/trust states
 * (Circle's top tier), coral-red for danger/SOS — chosen to read as
 * urgent and distinct from the brand accent, since SOS must never be
 * confusable with a routine action.
 */

export const dark = {
  background: "#0B0B12",
  surface: "#15151F",
  surfaceRaised: "#1D1D2A",
  border: "#2A2A3A",
  borderStrong: "#3D3D52",

  textPrimary: "#F6F6F9",
  textSecondary: "#A3A3B5",
  textTertiary: "#6E6E85",
  textInverse: "#0B0B12",

  accent: "#7C6AFF",
  accentPressed: "#6453E8",
  accentMuted: "#241F45",

  success: "#2FD999",
  warning: "#F5A623",
  danger: "#FF5A5F",
  info: "#4FA8FF",
} as const;

export const light = {
  background: "#FAFAFC",
  surface: "#FFFFFF",
  surfaceRaised: "#FFFFFF",
  border: "#E6E6EF",
  borderStrong: "#D1D1E0",

  textPrimary: "#15151F",
  textSecondary: "#5C5C70",
  textTertiary: "#8C8C9E",
  textInverse: "#FAFAFC",

  accent: "#6653E0",
  accentPressed: "#5440BE",
  accentMuted: "#EDEAFF",

  success: "#0F9D6E",
  warning: "#B9720A",
  danger: "#E1373D",
  info: "#2277D6",
} as const;

/** Trust tiers shown in the UI: Unverified → Verified → Circle, plus Blocked. */
export const trustTier = {
  unverified: { dark: dark.textTertiary, light: light.textTertiary },
  verified: { dark: dark.info, light: light.info },
  circle: { dark: dark.accent, light: light.accent },
  blocked: { dark: dark.danger, light: light.danger },
} as const;

/** A small, fixed set of avatar background colors, deterministically
 * picked per-user (see lib/avatar-color.ts) so the same person always
 * gets the same color without a lookup table. */
export const avatarPalette = [
  "#7C6AFF",
  "#2FD999",
  "#4FA8FF",
  "#F5A623",
  "#FF5A5F",
  "#E85DCE",
  "#5DD5E8",
  "#B98CFF",
] as const;

export type ColorPalette = Record<keyof typeof dark, string>;
export type TrustTierKey = keyof typeof trustTier;
