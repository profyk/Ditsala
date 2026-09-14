/**
 * Ditsala type scale — a high-contrast serif for the wordmark/headlines
 * (premium, editorial) paired with a clean grotesk for UI text (legible,
 * neutral). Ratio ~1.25 from a 15px UI base.
 */

export const fontFamily = {
  display: "'Fraunces', Georgia, 'Times New Roman', serif",
  body: "'Inter', -apple-system, 'Segoe UI', Roboto, sans-serif",
} as const;

export const fontWeight = {
  regular: "400",
  medium: "500",
  semibold: "600",
  bold: "700",
} as const;

export const typeScale = {
  displayXl: { fontFamily: fontFamily.display, fontSize: 48, lineHeight: 54, fontWeight: fontWeight.semibold },
  displayLg: { fontFamily: fontFamily.display, fontSize: 36, lineHeight: 42, fontWeight: fontWeight.semibold },
  headline: { fontFamily: fontFamily.display, fontSize: 28, lineHeight: 34, fontWeight: fontWeight.medium },
  title: { fontFamily: fontFamily.body, fontSize: 22, lineHeight: 28, fontWeight: fontWeight.semibold },
  bodyLg: { fontFamily: fontFamily.body, fontSize: 17, lineHeight: 24, fontWeight: fontWeight.regular },
  body: { fontFamily: fontFamily.body, fontSize: 15, lineHeight: 22, fontWeight: fontWeight.regular },
  bodySm: { fontFamily: fontFamily.body, fontSize: 13, lineHeight: 18, fontWeight: fontWeight.regular },
  caption: { fontFamily: fontFamily.body, fontSize: 12, lineHeight: 16, fontWeight: fontWeight.medium },
  overline: { fontFamily: fontFamily.body, fontSize: 11, lineHeight: 14, fontWeight: fontWeight.semibold },
} as const;

export type TypeScaleKey = keyof typeof typeScale;
