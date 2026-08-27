#!/usr/bin/env python3
"""Remove black matte from Star Piece logo PNG → transparent background."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

TCG_ROOT = Path(__file__).resolve().parent.parent
SRC = TCG_ROOT / "web" / "static" / "star-piece-logo-raw.png"
OUT = TCG_ROOT / "web" / "static" / "star-piece-logo.png"
BLACK_THRESHOLD = 42


def main() -> int:
    if not SRC.exists():
        print(f"Missing source: {SRC}", file=sys.stderr)
        return 1

    img = Image.open(SRC).convert("RGBA")
    px = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if r <= BLACK_THRESHOLD and g <= BLACK_THRESHOLD and b <= BLACK_THRESHOLD:
                px[x, y] = (r, g, b, 0)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, format="PNG", optimize=True)
    print(f"Wrote {OUT} ({w}x{h}, transparent background)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
