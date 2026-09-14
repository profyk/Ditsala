from PIL import Image, ImageDraw

# Exact values from packages/ui-tokens/src/colors.ts (dark palette)
BG = (0x0A, 0x0A, 0x0B)
ACCENT = (0xC8, 0xA0, 0x59)
ACCENT_MUTED = (0x3A, 0x32, 0x22)

SIZE = 1024
CX, CY = SIZE // 2, SIZE // 2


def draw_d(draw, center_x, cy, height, spine, stroke, fill=ACCENT, cut=BG):
    """
    A bold D monogram built from a flat rectangle (the spine) plus a
    concentric circle (the rounded bowl), then the same construction
    inset by `stroke` and filled with `cut` to hollow out a uniform-width
    counter. `center_x` is where the whole glyph is horizontally centered.
    """
    r = height // 2
    total_width = spine + r
    x_left = center_x - total_width // 2
    ccx = x_left + spine

    # pieslice (right half only) — a full ellipse would let its left half
    # bleed into the spine/counter region on the wrong side of ccx.
    draw.rectangle([x_left, cy - r, ccx, cy + r], fill=fill)
    draw.pieslice([ccx - r, cy - r, ccx + r, cy + r], -90, 90, fill=fill)

    r_inner = r - stroke
    inner_x_left = x_left + stroke
    draw.rectangle([inner_x_left, cy - r_inner, ccx, cy + r_inner], fill=cut)
    draw.pieslice([ccx - r_inner, cy - r_inner, ccx + r_inner, cy + r_inner], -90, 90, fill=cut)


# --- Universal / iOS icon: full square, background + mark ---
img = Image.new("RGB", (SIZE, SIZE), BG)
d = ImageDraw.Draw(img)
d.ellipse([CX - 460, CY - 460, CX + 460, CY + 460], outline=ACCENT_MUTED, width=4)
draw_d(d, CX, CY, height=416, spine=150, stroke=64)
img.save(r"C:\Users\profy\ditsala\docs\brand\icon-1024.png")

# --- Android adaptive icon foreground: transparent, mark only, safe-zone inset ---
fg = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
dfg = ImageDraw.Draw(fg)
draw_d(dfg, CX, CY, height=224, spine=80, stroke=34, cut=(0, 0, 0, 0))
fg.save(r"C:\Users\profy\ditsala\docs\brand\adaptive-icon-foreground.png")

print("done")
