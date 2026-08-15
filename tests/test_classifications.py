"""Tests for classifications.py — GICS + TradingView per-ticker taxonomy."""

import pytest

from pytvtools_core.classifications import (
    _fetch_constituents,
    _GICS_HIERARCHY,
    _GICS_CONSTITUENTS_STATIC,
    _gics_cache,
    get_gics_classifications,
)


def test_hierarchy_counts():
    assert len(_GICS_HIERARCHY) == 273
    levels = {}
    for r in _GICS_HIERARCHY.values():
        levels[r["level_num"]] = levels.get(r["level_num"], 0) + 1
    assert levels == {"1": 11, "2": 25, "3": 74, "4": 163}


def test_hierarchy_parent_links_resolve():
    # every non-sector code's parent must exist in the hierarchy
    for code, r in _GICS_HIERARCHY.items():
        if r["level_num"] == "1":
            continue
        assert r["parent_code"] in _GICS_HIERARCHY, (code, r["parent_code"])


def test_hierarchy_name_collision_building_products():
    # "Building Products" exists at BOTH industry (201020) and sub-industry
    # (20102010) level — name lookups must never use a full-name index.
    codes = [c for c, r in _GICS_HIERARCHY.items() if r["name"] == "Building Products"]
    assert "201020" in codes
    assert "20102010" in codes


def test_static_snapshot_shape():
    assert len(_GICS_CONSTITUENTS_STATIC) >= 490
    row = _GICS_CONSTITUENTS_STATIC[0]
    assert set(row) == {"symbol", "security", "sector", "sub_industry"}
    assert all("." not in r["symbol"] for r in _GICS_CONSTITUENTS_STATIC)


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """Never hit the network: constituents come from the static snapshot.

    ``get_gics_classifications()`` fetches ``constituents.csv`` on first call,
    so every test replaces the module-level ``_fetch_constituents`` with the
    static snapshot.  (The fallback test below calls the *imported* real
    function directly — unaffected by this module-attribute patch.)
    """
    monkeypatch.setattr(
        "pytvtools_core.classifications._fetch_constituents",
        lambda: [dict(r) for r in _GICS_CONSTITUENTS_STATIC],
    )


def _reset_cache():
    global _gics_cache
    _gics_cache = None


def test_rollup_apple():
    _reset_cache()
    rows = get_gics_classifications(symbol_map={"AAPL": "NASDAQ:AAPL"})
    aapl = [r for r in rows if r["symbol"] == "NASDAQ:AAPL"]
    assert len(aapl) == 1
    r = aapl[0]
    assert r["sector"] == "Information Technology"
    assert r["industry_group"] == "Technology Hardware & Equipment"
    assert r["industry"] == "Technology Hardware, Storage & Peripherals"
    assert r["sub_industry"] == "Technology Hardware, Storage & Peripherals"
    assert r["security"] == "Apple Inc."


def test_rollup_berkshire_dash_and_prefix():
    _reset_cache()
    rows = get_gics_classifications(symbol_map={"BRK-B": "NYSE:BRK.B"})
    brk = [r for r in rows if r["symbol"] == "NYSE:BRK.B"]
    assert len(brk) == 1
    assert brk[0]["sector"] == "Financials"
    assert brk[0]["sub_industry"] == "Multi-Sector Holdings"


def test_unmatched_symbol_stays_bare_dash():
    _reset_cache()
    rows = get_gics_classifications(symbol_map={})
    # pick a symbol known NOT to be prefixed by the empty map
    r = next(x for x in rows if x["symbol"].endswith("-B"))
    assert r["symbol"] == "BRK-B"


def test_fetch_failure_falls_back_to_static(monkeypatch):
    import sys
    from unittest import mock

    fake_pd = mock.MagicMock()
    fake_pd.read_csv.side_effect = Exception("network down")
    monkeypatch.setitem(sys.modules, "pandas", fake_pd)
    rows = _fetch_constituents()
    assert rows == [dict(r) for r in _GICS_CONSTITUENTS_STATIC]


def test_all_static_symbols_roll_up_cleanly():
    _reset_cache()
    rows = get_gics_classifications(symbol_map={})
    assert len(rows) == len(_GICS_CONSTITUENTS_STATIC)
    for r in rows:
        assert r["industry_group"], r
        assert r["industry"], r
        assert r["sector"], r
