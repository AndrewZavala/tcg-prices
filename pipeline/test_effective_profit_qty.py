"""Tests for CK-aware profitable quantity caps."""

from tcg_condition import CK_MAX_QTY_ORDER_MULTIPLIER, effective_profit_qty


def test_tcg_below_ck_cap_uses_tcg_qty():
    assert effective_profit_qty(3, 10) == 3


def test_tcg_equals_ck_cap_uses_tcg_qty():
    assert effective_profit_qty(4, 4) == 4


def test_tcg_above_ck_cap_uses_multiplier_times_ck():
    assert effective_profit_qty(100, 4) == 4 * CK_MAX_QTY_ORDER_MULTIPLIER
    assert CK_MAX_QTY_ORDER_MULTIPLIER == 2


def test_tcg_above_cap_but_below_multiplier_times_ck():
    # TCG=7, CK max=4 → 2× cap is 8 but only 7 available
    assert effective_profit_qty(7, 4) == 7


def test_missing_ck_max_falls_back_to_tcg():
    assert effective_profit_qty(25, None) == 25
    assert effective_profit_qty(25, 0) == 25


def test_zero_tcg_returns_zero():
    assert effective_profit_qty(0, 4) == 0
