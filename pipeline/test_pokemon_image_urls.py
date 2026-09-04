"""Tests for remote card image URL helpers."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pokemon_image_urls import (  # noqa: E402
    pokemon_com_image_urls,
    remote_image_bases,
)


def test_swshp_pokemon_com_includes_lugia_v() -> None:
    urls = pokemon_com_image_urls("swshp-SWSH301", "SWSH301")
    assert any(u.endswith("SWSHP_EN_SWSH301.png") for u in urls)


def test_remote_bases_include_pokemon_com_after_pokemontcg() -> None:
    bases = remote_image_bases(None, card_id="swshp-SWSH301", local_id="SWSH301")
    assert any("pokemontcg.io" in b for b in bases)
    assert any("assets.pokemon.com" in b and "SWSH301" in b for b in bases)


if __name__ == "__main__":
    test_swshp_pokemon_com_includes_lugia_v()
    test_remote_bases_include_pokemon_com_after_pokemontcg()
    print("ok")
