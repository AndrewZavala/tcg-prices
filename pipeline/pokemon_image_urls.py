"""Remote card-image URL helpers shared by download + API provenance.

Does not know about local /media paths — that lives in web/pokemon_api.py.
"""

from __future__ import annotations

# Keep in sync with web/pokemon_api._POKEMONTCG_SET_ALIASES
POKEMONTCG_SET_ALIASES: dict[str, str] = {
    "me01": "me1",
    "me02": "me2",
    "me02.5": "me2pt5",
    "me03": "me3",
    "me04": "me4",
    "me05": "me5",
    "sv01": "sv1",
    "sv02": "sv2",
    "sv03": "sv3",
    "sv03.5": "sv3pt5",
    "sv04": "sv4",
    "sv04.5": "sv4pt5",
    "sv05": "sv5",
    "sv06": "sv6",
    "sv06.5": "sv6pt5",
    "sv07": "sv7",
    "sv08": "sv8",
    "sv08.5": "sv8pt5",
    "sv09": "sv9",
    "sv10": "sv10",
    "sv10.5b": "zsv10pt5",
    "sv10.5w": "rsv10pt5",
    "sm3.5": "sm35",
    "sm7.5": "sm75",
    "swsh3.5": "swsh35",
    "swsh4.5": "swsh45",
    "swsh4.5sv": "swsh45sv",
    "swsh9.5tg": "swsh9tg",
    "swsh10.5": "pgo",
    "swsh10.5tg": "swsh10tg",
    "swsh11.5tg": "swsh11tg",
    "swsh12.5": "swsh12pt5",
    "swsh12.5tg": "swsh12tg",
    "swsh12.5gg": "swsh12pt5gg",
    "cel25cc": "cel25c",
}


def pokemontcg_image_urls(card_id: str | None, local_id: str | None = None) -> list[str]:
    """Candidate pokemontcg.io URLs (standard then hires)."""
    if not card_id or "-" not in card_id:
        return []
    set_part, local = card_id.split("-", 1)
    if local_id:
        local = str(local_id)
    api_set = POKEMONTCG_SET_ALIASES.get(set_part.lower(), set_part.lower())
    nums: list[str] = []
    raw = local
    nums.append(raw)
    if raw.isdigit():
        nums.append(str(int(raw)))
    elif raw.upper().startswith("CC") and raw[2:].isdigit():
        nums.append(f"{int(raw[2:])}_A")
    seen: set[str] = set()
    out: list[str] = []
    for num in nums:
        if num in seen:
            continue
        seen.add(num)
        out.append(f"https://images.pokemontcg.io/{api_set}/{num}.png")
        out.append(f"https://images.pokemontcg.io/{api_set}/{num}_hires.png")
    return out


def remote_image_bases(
    image_url: str | None,
    *,
    card_id: str | None = None,
    local_id: str | None = None,
) -> list[str]:
    """Ordered remote bases or absolute file URLs to try when mirroring."""
    bases: list[str] = []
    base = (image_url or "").strip()
    if base:
        bases.append(base)
    # Always allow pokemontcg fallbacks for gaps / bad TCGdex URLs
    bases.extend(pokemontcg_image_urls(card_id, local_id))
    # unique
    seen: set[str] = set()
    out: list[str] = []
    for b in bases:
        if b and b not in seen:
            seen.add(b)
            out.append(b)
    return out
