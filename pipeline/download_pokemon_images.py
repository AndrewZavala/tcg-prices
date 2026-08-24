#!/usr/bin/env python3
"""Download card art into local CARD_IMAGE_ROOT for first-party serving.

Layout:
  {CARD_IMAGE_ROOT}/cards/{card_id}/low.webp
  {CARD_IMAGE_ROOT}/cards/{card_id}/high.webp

Public URLs (via Caddy or FastAPI):
  /media/cards/{card_id}/low.webp
  /media/cards/{card_id}/high.webp

Remote image_url in Postgres stays as provenance; image_local marks readiness.

Examples:
  python download_pokemon_images.py
  python download_pokemon_images.py --set xy1 --limit 50
  python download_pokemon_images.py --force --dry-run
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests
from sqlalchemy import create_engine, text

from config import DATABASE_URL
from pokemon_image_urls import remote_image_bases

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None  # type: ignore

USER_AGENT = "SpellTagImageMirror/1.0"
REQUEST_DELAY_SEC = float(os.environ.get("CARD_IMAGE_DELAY_SEC", "0.08"))
CARD_IMAGE_ROOT = Path(os.environ.get("CARD_IMAGE_ROOT", "/data/card-images"))


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "*/*"})
    return s


def _remote_candidates(
    image_url: str | None, card_id: str, local_id: str | None
) -> dict[str, list[str]]:
    """Return candidate remote URLs for low/high sizes."""
    bases = remote_image_bases(image_url, card_id=card_id, local_id=local_id)
    low: list[str] = []
    high: list[str] = []
    for base in bases:
        if base.endswith((".webp", ".png", ".jpg", ".jpeg")):
            high.append(base)
            if "_hires." in base:
                low.append(base.replace("_hires.", "."))
            low.append(base)
        else:
            low.append(f"{base}/low.webp")
            low.append(f"{base}/high.webp")
            high.append(f"{base}/high.webp")
            high.append(f"{base}/low.webp")

    def uniq(rows: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for u in rows:
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out

    return {"low": uniq(low), "high": uniq(high)}


def _to_webp_bytes(content: bytes, content_type: str | None) -> bytes:
    ct = (content_type or "").lower()
    if "webp" in ct or (
        len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    ):
        return content
    if Image is None:
        return content
    img = Image.open(io.BytesIO(content))
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=82, method=4)
    return buf.getvalue()


def _fetch_webp(session: requests.Session, urls: list[str]) -> bytes | None:
    for url in urls:
        try:
            resp = session.get(url, timeout=45)
            if resp.status_code != 200 or not resp.content:
                continue
            return _to_webp_bytes(resp.content, resp.headers.get("Content-Type"))
        except requests.RequestException:
            continue
    return None


def card_dir(card_id: str) -> Path:
    safe = card_id.replace("..", "").replace("/", "_").replace("\\", "_")
    return CARD_IMAGE_ROOT / "cards" / safe


def files_ready(card_id: str) -> bool:
    d = card_dir(card_id)
    return (d / "low.webp").is_file() and (d / "high.webp").is_file()


def download_one(
    session: requests.Session,
    *,
    card_id: str,
    local_id: str | None,
    image_url: str | None,
    dry_run: bool,
) -> bool:
    targets = _remote_candidates(image_url, card_id, local_id)
    if dry_run:
        print(f"  would fetch {card_id} low={targets['low'][:2]} high={targets['high'][:2]}")
        return True

    low = _fetch_webp(session, targets["low"])
    time.sleep(REQUEST_DELAY_SEC)
    high = _fetch_webp(session, targets["high"])
    if not low and not high:
        return False
    if low and not high:
        high = low
    if high and not low:
        low = high
    assert low and high
    dest = card_dir(card_id)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "low.webp").write_bytes(low)
    (dest / "high.webp").write_bytes(high)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Mirror Pokémon card art locally")
    parser.add_argument("--set", dest="set_id", help="Only this set_id")
    parser.add_argument("--limit", type=int, default=0, help="Max cards to process")
    parser.add_argument("--force", action="store_true", help="Re-download even if image_local")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--mark-existing",
        action="store_true",
        help="Only mark image_local when files already exist on disk",
    )
    args = parser.parse_args()

    if Image is None:
        print("Pillow is required (pip install Pillow)", file=sys.stderr)
        return 1

    CARD_IMAGE_ROOT.mkdir(parents=True, exist_ok=True)
    (CARD_IMAGE_ROOT / "cards").mkdir(parents=True, exist_ok=True)

    engine = create_engine(DATABASE_URL, future=True)
    where = ["TRUE"]
    params: dict[str, Any] = {}
    if not args.force and not args.mark_existing:
        where.append("(COALESCE(image_local, FALSE) = FALSE)")
    if args.set_id:
        where.append("set_id = :set_id")
        params["set_id"] = args.set_id

    sql = f"""
        SELECT id, local_id, image_url, COALESCE(image_local, FALSE) AS image_local
        FROM pokemon_cards
        WHERE {" AND ".join(where)}
        ORDER BY set_id, id
    """
    if args.limit and args.limit > 0:
        sql += " LIMIT :limit"
        params["limit"] = args.limit

    session = _session()
    ok = fail = skip = 0
    with engine.begin() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
        print(f"Processing {len(rows)} card(s); root={CARD_IMAGE_ROOT}")
        for row in rows:
            card_id = str(row["id"])
            if args.mark_existing:
                if files_ready(card_id):
                    conn.execute(
                        text(
                            """
                            UPDATE pokemon_cards
                            SET image_local = TRUE, image_local_at = NOW()
                            WHERE id = :id
                            """
                        ),
                        {"id": card_id},
                    )
                    ok += 1
                else:
                    skip += 1
                continue

            if not args.force and files_ready(card_id):
                conn.execute(
                    text(
                        """
                        UPDATE pokemon_cards
                        SET image_local = TRUE,
                            image_local_at = COALESCE(image_local_at, NOW())
                        WHERE id = :id
                        """
                    ),
                    {"id": card_id},
                )
                skip += 1
                continue

            try:
                success = download_one(
                    session,
                    card_id=card_id,
                    local_id=row.get("local_id"),
                    image_url=row.get("image_url"),
                    dry_run=args.dry_run,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"  FAIL {card_id}: {exc}")
                fail += 1
                continue

            if not success:
                print(f"  MISS {card_id}")
                fail += 1
                continue

            if not args.dry_run:
                conn.execute(
                    text(
                        """
                        UPDATE pokemon_cards
                        SET image_local = TRUE, image_local_at = NOW()
                        WHERE id = :id
                        """
                    ),
                    {"id": card_id},
                )
            ok += 1
            if ok % 50 == 0:
                print(f"  … {ok} saved / {fail} miss / {skip} skip")

    print(f"Done — saved={ok} miss={fail} skip={skip}")
    return 0 if fail == 0 or ok > 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
