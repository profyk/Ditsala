/**
 * Ditsala palette — dark-first, restrained, private-members'-club aesthetic.
 * Deliberately avoids WhatsApp green / Telegram-Signal blue as primary chrome.
 * A single accent (gold) is reserved for calls-to-action and the Circle trust tier.
 */

export const dark = {
  background: "#0A0A0B",
  surface: "#141518",
  surfaceRaised: "#1C1E22",
  border: "#2A2C31",
  borderStrong: "#3A3D44",

  textPrimary: "#F5F5F2",
  textSecondary: "#9B9EA6",
  textTertiary: "#6B6E76",
  textInverse: "#0A0A0B",

  accent: "#C8A059",
  accentPressed: "#B08B47",
  accentMuted: "#3A3222",

  success: "#4C9A8E",
  warning: "#D9A441",
  danger: "#C1493A",
  info: "#5B8AA6",
} as const;

export const light = {
  background: "#F7F6F3",
  surface: "#FFFFFF",
  surfaceRaised: "#FFFFFF",
  border: "#E3E1DB",
  borderStrong: "#CFCCC3",

  textPrimary: "#161615",
  textSecondary: "#5A5B57",
  textTertiary: "#8B8C87",
  textInverse: "#F7F6F3",

  accent: "#9C7A34",
  accentPressed: "#7F6329",
  accentMuted: "#F1E6D1",

  success: "#3B7A70",
  warning: "#A9781F",
  danger: "#9E3B2E",
  info: "#3E6E87",
} as const;

/** Trust tiers shown in the UI: Unverified → Verified → Circle, plus Blocked. */
export const trustTier = {
  unverified: { dark: dark.textTertiary, light: light.textTertiary },
  verified: { dark: dark.info, light: light.info },
  circle: { dark: dark.accent, light: light.accent },
  blocked: { dark: dark.danger, light: light.danger },
} as const;

export type ColorPalette = typeof dark;
export type TrustTierKey = keyof typeof trustTier;
