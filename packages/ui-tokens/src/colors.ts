/**
 * Ditsala palette v3 — replaces the v2 dark-first indigo-violet identity
 * with a lighter, warmer "premium messaging" look modeled on a real
 * reference design (a fully fleshed-out Ditsala-branded chat app UI
 * built separately, whose exact tokens this file mirrors — see
 * CLAUDE.md's rebrand entry for the source and rationale). Fresh green
 * is now the single brand/CTA accent (used for every send button, FAB,
 * unread badge, and primary action), deep navy is the secondary brand
 * identity color for hero/VIP surfaces, and warm gold marks VIP/premium
 * specifically — distinct from `warning`, which happens to share its
 * hex value but is semantically a different concept.
 */

export const dark = {
  background: "#050B20",
  surface: "#0F1A38",
  surfaceRaised: "#16224A",
  border: "#1E2A50",
  borderStrong: "#2C3A64",

  textPrimary: "#F4F6F9",
  textSecondary: "#8A97B8",
  textTertiary: "#5E6B8C",
  textInverse: "#050B20",

  accent: "#5FB325",
  accentPressed: "#4C9420",
  accentMuted: "#123318",

  success: "#5FB325",
  warning: "#F5A623",
  danger: "#F87171",
  info: "#7C93E8",

  brandNavy: "#0B1E5B",
  gold: "#F5A623",
} as const;

export const light = {
  background: "#F4F6F9",
  surface: "#FFFFFF",
  surfaceRaised: "#FFFFFF",
  border: "#E2E8F0",
  borderStrong: "#CBD5E1",

  textPrimary: "#050B20",
  textSecondary: "#64748B",
  textTertiary: "#94A3B8",
  textInverse: "#FFFFFF",

  accent: "#5FB325",
  accentPressed: "#4C9420",
  accentMuted: "#EAF5E4",

  success: "#5FB325",
  warning: "#F5A623",
  danger: "#E63946",
  info: "#0B1E5B",

  brandNavy: "#0B1E5B",
  gold: "#F5A623",
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
  "#5FB325",
  "#0B1E5B",
  "#F5A623",
  "#2277D6",
  "#E63946",
  "#B98CFF",
  "#5DD5E8",
  "#E85DCE",
] as const;

export type ColorPalette = Record<keyof typeof dark, string>;
export type TrustTierKey = keyof typeof trustTier;
