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

# Official pokemon.com CMS paths for promo sets (TCGdex/pokemontcg often lag).
# https://assets.pokemon.com/assets/cms2/img/cards/web/{CODE}/{CODE}_EN_{num}.png
POKEMON_COM_PROMO_CODES: dict[str, str] = {
    "swshp": "SWSHP",
    "smp": "SMP",
    "svp": "SVP",
    "xyp": "XYP",
    "bwp": "BWP",
    "mep": "MEP",
    "hgssp": "HGSSP",
    "dpp": "DPP",
    "np": "NP",
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


def pokemon_com_image_urls(card_id: str | None, local_id: str | None = None) -> list[str]:
    """Candidate assets.pokemon.com URLs (best for missing promo art)."""
    if not card_id or "-" not in card_id:
        return []
    set_part, local = card_id.split("-", 1)
    if local_id:
        local = str(local_id)
    code = POKEMON_COM_PROMO_CODES.get(set_part.lower())
    if not code:
        return []

    nums: list[str] = [local]
    # SVP / numeric promos on pokemon.com are often unpadded ("1" not "001").
    if local.isdigit():
        nums.append(str(int(local)))
    upper = local.upper()
    if upper.startswith("SWSH") and upper[4:].isdigit():
        nums.append(upper[4:])
        nums.append(str(int(upper[4:])))
    if upper.startswith("SM") and upper[2:].isdigit():
        nums.append(f"SM{int(upper[2:]):02d}")
        nums.append(f"SM{upper[2:]}")
    if upper.startswith("XY") and upper[2:].isdigit():
        nums.append(f"XY{int(upper[2:]):02d}")
    if upper.startswith("BW") and upper[2:].isdigit():
        nums.append(f"BW{int(upper[2:]):02d}")

    seen: set[str] = set()
    out: list[str] = []
    for num in nums:
        if not num or num in seen:
            continue
        seen.add(num)
        out.append(
            f"https://assets.pokemon.com/assets/cms2/img/cards/web/{code}/{code}_EN_{num}.png"
        )
        out.append(
            f"https://www.pokemon.com/static-assets/content-assets/cms2/img/cards/web/{code}/{code}_EN_{num}.png"
        )
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
    # Always allow pokemontcg + official pokemon.com fallbacks for gaps / bad TCGdex URLs
    bases.extend(pokemontcg_image_urls(card_id, local_id))
    bases.extend(pokemon_com_image_urls(card_id, local_id))
    seen: set[str] = set()
    out: list[str] = []
    for b in bases:
        if b and b not in seen:
            seen.add(b)
            out.append(b)
    return out
