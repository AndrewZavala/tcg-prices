"""Build TCGplayer product and Impact affiliate URLs."""

from __future__ import annotations

import os
import re
from urllib.parse import quote, urlencode

TCGPLAYER_PROGRAM_ID = "21018"
_PARTNER_LINK_RE = re.compile(
    r"^https://partner\.tcgplayer\.com/c/(\d+)/(\d+)/(\d+)",
    re.I,
)


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def partner_link_base() -> str | None:
    """Impact tracking-link base (no ``?u=`` yet).

    Set ``TCGPLAYER_PARTNER_LINK`` to the full API link from Impact, or
    ``TCGPLAYER_PARTNER_ID`` + ``TCGPLAYER_AD_ID`` (program id defaults to 21018).
    """
    link = _env("TCGPLAYER_PARTNER_LINK")
    if link:
        base = link.split("?", 1)[0].rstrip("/")
        if _PARTNER_LINK_RE.match(base):
            return base
    partner = _env("TCGPLAYER_PARTNER_ID")
    ad = _env("TCGPLAYER_AD_ID")
    if partner and ad:
        return f"https://partner.tcgplayer.com/c/{partner}/{ad}/{TCGPLAYER_PROGRAM_ID}"
    return None


def tcgplayer_product_url(product_id: str | None, *, foil: bool = False) -> str:
    pid = str(product_id or "").strip().replace(".0", "")
    if not pid or pid.lower() in {"nan", "none"}:
        return ""
    params: dict[str, str] = {"Language": "English"}
    if foil:
        params["Printing"] = "Foil"
    return f"https://www.tcgplayer.com/product/{pid}?{urlencode(params)}"


def tcgplayer_pokemon_search_url(name: str, set_name: str, local_id: str) -> str:
    q = " ".join(part for part in (name, set_name, f"#{local_id}") if part)
    return (
        "https://www.tcgplayer.com/search/pokemon/product?"
        + urlencode({"q": q, "productLineName": "pokemon"})
    )


def tcgplayer_affiliate_url(destination: str) -> str:
    """Wrap a tcgplayer.com destination in the Impact redirect when configured."""
    dest = (destination or "").strip()
    if not dest:
        return ""
    base = partner_link_base()
    if not base:
        return dest
    return f"{base}?u={quote(dest, safe='')}"


def pokemon_buy_url(
    *,
    product_id: str | None,
    name: str,
    set_name: str,
    local_id: str,
) -> str:
    """Affiliate-wrapped TCGplayer link for one Pokémon printing."""
    dest = tcgplayer_product_url(product_id) or tcgplayer_pokemon_search_url(
        name, set_name, local_id
    )
    return tcgplayer_affiliate_url(dest)
