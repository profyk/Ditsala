import { describe, expect, it } from "vitest";
import { dark, light, trustTier, typeScale, spacing, radius } from "./index";

describe("ui-tokens", () => {
  it("dark and light palettes expose the same keys", () => {
    expect(Object.keys(dark).sort()).toEqual(Object.keys(light).sort());
  });

  it("every trust tier resolves in both themes", () => {
    for (const tier of Object.values(trustTier)) {
      expect(tier.dark).toMatch(/^#[0-9A-Fa-f]{6}$/);
      expect(tier.light).toMatch(/^#[0-9A-Fa-f]{6}$/);
    }
  });

  it("type scale sizes are monotonically ordered top to bottom", () => {
    const order = [
      "displayXl",
      "displayLg",
      "headline",
      "title",
      "bodyLg",
      "body",
      "bodySm",
      "caption",
      "overline",
    ] as const;
    for (let i = 1; i < order.length; i++) {
      expect(typeScale[order[i - 1]].fontSize).toBeGreaterThan(typeScale[order[i]].fontSize);
    }
  });

  it("spacing and radius scales are non-negative and ascending", () => {
    const spacingValues = Object.values(spacing);
    const radiusValues = Object.values(radius);
    expect([...spacingValues].sort((a, b) => a - b)).toEqual(spacingValues);
    expect([...radiusValues].sort((a, b) => a - b)).toEqual(radiusValues);
  });
});
