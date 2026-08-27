#!/usr/bin/env python3
"""Recolor original bubbly Star Piece logo for readability (geometry unchanged)."""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent / "web" / "static"
# Prefer raw (opaque black bg) if present; else transparent PNG
SRC_CANDIDATES = [
    ROOT / "star-piece-logo-raw.png",
    ROOT / "star-piece-logo.png",
]
OUT = ROOT / "star-piece-logo-readable.png"
CANONICAL = ROOT / "star-piece-logo.png"
BG_THR = 42


def rgb_to_hsv(r: float, g: float, b: float) -> tuple[float, float, float]:
    r, g, b = r / 255.0, g / 255.0, b / 255.0
    mx, mn = max(r, g, b), min(r, g, b)
    df = mx - mn
    if df == 0:
        h = 0.0
    elif mx == r:
        h = (60 * ((g - b) / df) + 360) % 360
    elif mx == g:
        h = (60 * ((b - r) / df) + 120) % 360
    else:
        h = (60 * ((r - g) / df) + 240) % 360
    s = 0.0 if mx == 0 else df / mx
    return h, s, mx


def hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    c = v * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = v - c
    if 0 <= h < 60:
        rp, gp, bp = c, x, 0.0
    elif 60 <= h < 120:
        rp, gp, bp = x, c, 0.0
    elif 120 <= h < 180:
        rp, gp, bp = 0.0, c, x
    elif 180 <= h < 240:
        rp, gp, bp = 0.0, x, c
    elif 240 <= h < 300:
        rp, gp, bp = x, 0.0, c
    else:
        rp, gp, bp = c, 0.0, x
    return (
        int(round((rp + m) * 255)),
        int(round((gp + m) * 255)),
        int(round((bp + m) * 255)),
    )


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def recolor_pixel(r: int, g: int, b: int, a: int) -> tuple[int, int, int, int]:
    if a < 8:
        return r, g, b, a
    # Near-black → transparent (if working from raw)
    if r <= BG_THR and g <= BG_THR and b <= BG_THR:
        return 0, 0, 0, 0
    # Keep whites / gloss highlights
    if r >= 235 and g >= 235 and b >= 235:
        return r, g, b, a

    h, s, v = rgb_to_hsv(r, g, b)

    # Purple / magenta extrusion + star (cooler magenta–violet)
    if 270 <= h <= 330 and s >= 0.35 and v >= 0.25:
        # Darken extrusion for separation from pink faces
        s = clamp01(s * 1.05)
        v = clamp01(v * 0.72)
        nr, ng, nb = hsv_to_rgb(h, s, v)
        return nr, ng, nb, a

    # Pink letter faces (rose / hot pink)
    if (h >= 320 or h <= 20) and s >= 0.15 and v >= 0.35:
        # Push toward lighter cream-rose; tame hot pinks
        s = clamp01(s * 0.78)
        v = clamp01(min(0.98, v * 1.12 + 0.06))
        # Bias slightly toward peach so stripes stay distinct
        if h > 340 or h < 10:
            h = (h - 8) % 360
        nr, ng, nb = hsv_to_rgb(h, s, v)
        return nr, ng, nb, a

    return r, g, b, a


def main() -> int:
    src = next((p for p in SRC_CANDIDATES if p.exists()), None)
    if src is None:
        raise SystemExit("No star-piece-logo source found")

    img = Image.open(src).convert("RGBA")
    px = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            px[x, y] = recolor_pixel(*px[x, y])
    img.save(OUT, format="PNG", optimize=True)
    img.save(CANONICAL, format="PNG", optimize=True)
    print(f"Wrote {OUT} and {CANONICAL} from {src.name} ({w}x{h})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
