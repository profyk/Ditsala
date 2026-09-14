# DITSALA app icon

`icon-1024.png` — the universal/iOS app icon (1024×1024, opaque, no baked-in corner rounding — the OS applies its own mask).
`adaptive-icon-foreground.png` — Android adaptive icon foreground layer (1024×1024, transparent background, mark inset to Android's ~66% safe zone). Pair it with a flat background color, not an image — see below.

## Design

A bold "D" monogram, built from a flat spine + a concentric rounded bowl (no font glyph — the shape is drawn from rectangles/pie-slices for pixel-perfect geometric consistency at any size), plus a hairline ring nodding to the product's **Circle** trust tier without drawing an actual chat bubble.

This replaces an earlier candidate icon (blue/purple gradient chat-bubble mark) that was rejected as an exact match for the "no bubble chrome, must not resemble WhatsApp/Telegram/Signal" rule in `docs/DITSALA_MASTER_SPEC.md` §2.

Colors are pulled directly from `packages/ui-tokens/src/colors.ts` (`dark` palette) so the icon and the in-app UI never drift apart:

| Element | Token | Hex |
|---|---|---|
| Background | `dark.background` | `#0A0A0B` |
| Mark | `dark.accent` | `#C8A059` |
| Hairline ring | `dark.accentMuted` | `#3A3222` |

## Regenerating

`generate_icon.py` is the source of truth — a Pillow script, not a hand-edited image — so the mark can be resized/retuned without a design tool:

```
python docs/brand/generate_icon.py
```

## Wiring in (Phase 2, when `apps/mobile` is scaffolded)

Copy into the Expo project and reference from `app.json`:

```
apps/mobile/assets/icon.png                     ← icon-1024.png
apps/mobile/assets/adaptive-icon-foreground.png ← adaptive-icon-foreground.png
```

```json
{
  "expo": {
    "icon": "./assets/icon.png",
    "android": {
      "adaptiveIcon": {
        "foregroundImage": "./assets/adaptive-icon-foreground.png",
        "backgroundColor": "#0A0A0B"
      }
    }
  }
}
```
