/** Generous whitespace over dense chrome — 4px base unit. */
export const spacing = {
  none: 0,
  xxs: 4,
  xs: 8,
  sm: 12,
  md: 16,
  lg: 20,
  xl: 24,
  xxl: 32,
  xxxl: 40,
  huge: 64,
} as const;

/**
 * v2 — softer, more generous rounding than the original "restrained,
 * no playful chrome" scale: still no full pill-shaped chat bubbles
 * (`full` is reserved for avatars, badges, and circular icon buttons,
 * not message bubbles), but cards/sheets/buttons now read as a modern
 * app rather than a flat, sharp-cornered one.
 */
export const radius = {
  none: 0,
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  full: 9999,
} as const;

export type SpacingKey = keyof typeof spacing;
export type RadiusKey = keyof typeof radius;
