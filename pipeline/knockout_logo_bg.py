#!/usr/bin/env python3
"""Knock out near-black backgrounds on brand logo PNGs."""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent / "web" / "static"
PAIRS = [
    ("comet-shard-logo-raw.png", "comet-shard-logo.png"),
    ("ultra-space-logo-raw.png", "ultra-space-logo.png"),
    ("star-piece-logo-v2-raw.png", "star-piece-logo-v2.png"),
]
THR = 42


def main() -> int:
    for src_name, out_name in PAIRS:
        src = ROOT / src_name
        out = ROOT / out_name
        img = Image.open(src).convert("RGBA")
        px = img.load()
        w, h = img.size
        for y in range(h):
            for x in range(w):
                r, g, b, a = px[x, y]
                if r <= THR and g <= THR and b <= THR:
                    px[x, y] = (r, g, b, 0)
        img.save(out, format="PNG", optimize=True)
        print(f"Wrote {out} ({w}x{h})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
