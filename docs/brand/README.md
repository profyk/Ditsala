# DITSALA app icon

**Current design (replaces the earlier programmatic "D" monogram below):** a user-supplied artwork — a solid black square canvas with a gold "D" whose bowl tapers into a speech-bubble tail (a pointed lower-left corner) enclosing a three-dot ellipsis, brushed-gold gradient fill. Saved as `icon-1024.png`. (A refined pass of this same artwork replaced an earlier iteration — same concept, cleaner geometry.)

**Important limitation:** this artwork is a single flattened image (opaque black background baked in, no isolated glyph-on-transparent layer). That's exactly right for `icon.png` (the universal/iOS icon — always opaque, the OS applies its own corner mask). For Android's adaptive icon, which composites a separate foreground + background and lets the OS apply parallax/masking, the *correct* asset would be just the glyph on a transparent background — we don't have that layer, so:

- `adaptive-icon-foreground.png` is the same flattened artwork (Android will mask it into its own shape — slightly imperfect since our image already has its own rounded-square edge baked in, but visually consistent and functional).
- `adaptive-icon-background.png` is a flat `#0A0A0B` fill (the brand background token) so any visible edge blends rather than showing a seam.
- `adaptive-icon-monochrome.png` (Android 13+ themed icons) is a grayscale conversion of the same flattened artwork, not a true alpha silhouette — same root limitation.

If a properly isolated glyph-on-transparent version of this artwork becomes available later, regenerate the adaptive layers from that instead and drop the background-image workaround for a plain `backgroundColor` (simpler, and how the original monogram design below did it).

## Wiring

```
apps/mobile/assets/icon.png                     ← docs/brand/icon-1024.png
apps/mobile/assets/android-icon-foreground.png  ← docs/brand/adaptive-icon-foreground.png
apps/mobile/assets/android-icon-background.png  ← docs/brand/adaptive-icon-background.png
apps/mobile/assets/android-icon-monochrome.png  ← docs/brand/adaptive-icon-monochrome.png
apps/mobile/assets/favicon.png                  ← docs/brand/favicon.png
apps/mobile/assets/splash-icon.png              ← docs/brand/splash-icon.png
```

Already reflected in `apps/mobile/app.json`'s `expo.icon`/`expo.android.adaptiveIcon`/`expo.web.favicon`/`expo.splash` fields — no config change needed when swapping the source image, only the asset files.

---

## Earlier design (superseded, kept for history)

A bold "D" monogram, built from a flat spine + a concentric rounded bowl (no font glyph — the shape is drawn from rectangles/pie-slices for pixel-perfect geometric consistency at any size), plus a hairline ring nodding to the product's **Circle** trust tier without drawing an actual chat bubble.

This replaced an even earlier candidate icon (blue/purple gradient chat-bubble mark) that was rejected as an exact match for the "no bubble chrome, must not resemble WhatsApp/Telegram/Signal" rule in `docs/DITSALA_MASTER_SPEC.md` §2. It has since itself been superseded by the design above.

Colors were pulled directly from `packages/ui-tokens/src/colors.ts` (`dark` palette):

| Element | Token | Hex |
|---|---|---|
| Background | `dark.background` | `#0A0A0B` |
| Mark | `dark.accent` | `#C8A059` |
| Hairline ring | `dark.accentMuted` | `#3A3222` |

Regenerate it (if ever reverting) via:

```
python docs/brand/generate_icon.py
```
