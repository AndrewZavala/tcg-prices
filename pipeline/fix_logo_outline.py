#!/usr/bin/env python3
"""Rebuild a solid continuous white outer stroke on star-piece-logo-v2."""

from collections import deque
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent / "web" / "static"
SRC = ROOT / "star-piece-logo-v2-raw.png"
OUT = ROOT / "star-piece-logo-v2.png"

BG_THR = 42
ALPHA_THR = 8
WHITE_THR = 220
STRIP_WHITE_PX = 32
STROKE_PX = 26


def knock_black(img: Image.Image) -> None:
    px = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if r <= BG_THR and g <= BG_THR and b <= BG_THR:
                px[x, y] = (0, 0, 0, 0)


def flood_exterior(img: Image.Image) -> Image.Image:
    w, h = img.size
    px = img.load()
    ext = Image.new("L", (w, h), 0)
    ep = ext.load()
    q: deque[tuple[int, int]] = deque()

    def try_push(x: int, y: int) -> None:
        if not (0 <= x < w and 0 <= y < h) or ep[x, y]:
            return
        if px[x, y][3] > ALPHA_THR:
            return
        ep[x, y] = 255
        q.append((x, y))

    for x in range(w):
        try_push(x, 0)
        try_push(x, h - 1)
    for y in range(h):
        try_push(0, y)
        try_push(w - 1, y)
    while q:
        x, y = q.popleft()
        try_push(x - 1, y)
        try_push(x + 1, y)
        try_push(x, y - 1)
        try_push(x, y + 1)
    return ext


def is_near_white(r: int, g: int, b: int) -> bool:
    return r >= WHITE_THR and g >= WHITE_THR and b >= WHITE_THR


def main() -> int:
    logo = Image.open(SRC).convert("RGBA")
    knock_black(logo)
    w, h = logo.size
    px = logo.load()

    # Strip generated outer white (often broken); keep interior letter strokes
    exterior = flood_exterior(logo)
    near_ext = exterior.filter(ImageFilter.MaxFilter(STRIP_WHITE_PX * 2 + 1))
    nep = near_ext.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a > ALPHA_THR and nep[x, y] == 255 and is_near_white(r, g, b):
                px[x, y] = (0, 0, 0, 0)

    exterior = flood_exterior(logo)
    ep = exterior.load()
    content = Image.new("L", (w, h), 0)
    cp = content.load()
    for y in range(h):
        for x in range(w):
            if ep[x, y] == 0:
                cp[x, y] = 255

    # Close small silhouette gaps, then dilate for a solid stroke ring
    closed = content.filter(ImageFilter.MaxFilter(11)).filter(ImageFilter.MinFilter(11))
    dilated = closed.filter(ImageFilter.MaxFilter(STROKE_PX * 2 + 1))
    dp = dilated.load()

    outline = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    op = outline.load()
    for y in range(h):
        for x in range(w):
            if dp[x, y] == 255 and ep[x, y] == 255:
                op[x, y] = (255, 255, 255, 255)

    result = Image.alpha_composite(outline, logo)
    result.save(OUT, format="PNG", optimize=True)

    for name in (
        "star-piece-logo-v2-p-crop.png",
        "star-piece-logo-v2-gap-debug.png",
        "star-piece-logo-v2-bottom-mask.png",
    ):
        p = ROOT / name
        if p.exists():
            p.unlink()

    print(f"Wrote {OUT} (solid {STROKE_PX}px outer stroke)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
