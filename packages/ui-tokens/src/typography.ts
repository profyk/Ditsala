/**
 * Ditsala type scale v2 — a single clean grotesk (Inter) for everything,
 * hierarchy carried by size/weight/tracking rather than mixing a second
 * display family. The original scale paired Inter with Fraunces (a
 * serif) for headlines, but Fraunces was never actually loaded as a
 * font asset (see git history) — every "display" style silently fell
 * back to the system serif, a real gap this redesign closes by not
 * promising a typeface that isn't there, rather than finally wiring in
 * font loading for a look the redesign has moved away from anyway.
 */

export const fontFamily = {
  display: "'Inter', -apple-system, 'Segoe UI', Roboto, sans-serif",
  body: "'Inter', -apple-system, 'Segoe UI', Roboto, sans-serif",
} as const;

export const fontWeight = {
  regular: "400",
  medium: "500",
  semibold: "600",
  bold: "700",
  extrabold: "800",
} as const;

export const typeScale = {
  displayXl: { fontFamily: fontFamily.display, fontSize: 40, lineHeight: 46, fontWeight: fontWeight.extrabold, letterSpacing: -0.5 },
  displayLg: { fontFamily: fontFamily.display, fontSize: 32, lineHeight: 38, fontWeight: fontWeight.extrabold, letterSpacing: -0.3 },
  headline: { fontFamily: fontFamily.display, fontSize: 24, lineHeight: 30, fontWeight: fontWeight.bold, letterSpacing: -0.2 },
  title: { fontFamily: fontFamily.body, fontSize: 20, lineHeight: 26, fontWeight: fontWeight.semibold },
  bodyLg: { fontFamily: fontFamily.body, fontSize: 17, lineHeight: 24, fontWeight: fontWeight.regular },
  body: { fontFamily: fontFamily.body, fontSize: 15, lineHeight: 22, fontWeight: fontWeight.regular },
  bodySm: { fontFamily: fontFamily.body, fontSize: 13, lineHeight: 18, fontWeight: fontWeight.regular },
  caption: { fontFamily: fontFamily.body, fontSize: 12, lineHeight: 16, fontWeight: fontWeight.medium },
  overline: { fontFamily: fontFamily.body, fontSize: 11, lineHeight: 14, fontWeight: fontWeight.semibold },
} as const;

export type TypeScaleKey = keyof typeof typeScale;
