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


def test_cel25cc_blastoise_uses_reprint_number() -> None:
    from pokemon_image_urls import pokemontcg_image_urls

    urls = pokemontcg_image_urls("cel25cc-CC001", "CC001")
    assert "https://images.pokemontcg.io/cel25c/2_A_hires.png" in urls
    assert "https://images.pokemontcg.io/cel25c/1_A_hires.png" not in urls


def test_mep_alakazam_falls_back_to_tcgdex_and_limitless() -> None:
    bases = remote_image_bases(
        None, card_id="mep-003", local_id="003",
        set_id="mep", series_id="me", tcg_online_code="MEP",
    )
    assert "https://assets.tcgdex.net/en/me/mep/003" in bases
    assert (
        "https://limitlesstcg.nyc3.cdn.digitaloceanspaces.com/tpci/MEP/MEP_003_R_EN_LG.png"
        in bases
    )


def test_limitless_skips_non_numeric_numbers() -> None:
    from pokemon_image_urls import limitless_image_url

    assert limitless_image_url("SSP", "TG01") is None
    assert limitless_image_url(None, "001") is None


def test_unown_and_hgss_promos_use_pokemontcg_set_ids() -> None:
    from pokemon_image_urls import pokemontcg_image_urls

    assert "https://images.pokemontcg.io/ex10/E_hires.png" in pokemontcg_image_urls("exu-E", "E")
    assert "https://images.pokemontcg.io/ex10/question_hires.png" in pokemontcg_image_urls("exu-?", "?")
    assert "https://images.pokemontcg.io/hsp/HGSS17_hires.png" in pokemontcg_image_urls(
        "hgssp-HGSS17", "HGSS17"
    )


if __name__ == "__main__":
    test_swshp_pokemon_com_includes_lugia_v()
    test_remote_bases_include_pokemon_com_after_pokemontcg()
    test_cel25cc_blastoise_uses_reprint_number()
    test_mep_alakazam_falls_back_to_tcgdex_and_limitless()
    test_limitless_skips_non_numeric_numbers()
    test_unown_and_hgss_promos_use_pokemontcg_set_ids()
    print("ok")
