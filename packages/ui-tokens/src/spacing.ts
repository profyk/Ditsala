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
 * Deliberately restrained corner radii — no pill-shaped chat bubbles,
 * no playful over-rounded chrome (that's WhatsApp/iMessage/Signal territory).
 */
export const radius = {
  none: 0,
  sm: 2,
  md: 4,
  lg: 8,
} as const;

export type SpacingKey = keyof typeof spacing;
export type RadiusKey = keyof typeof radius;
