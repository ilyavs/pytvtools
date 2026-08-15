"""Tests for classifications.py — GICS + TradingView per-ticker taxonomy."""

from unittest import mock

import pytest

from pytvtools_core.classifications import (
    _fetch_constituents,
    _GICS_HIERARCHY,
    _GICS_CONSTITUENTS_STATIC,
    _gics_cache,
    classification_rows,
    get_gics_classifications,
    get_tv_classifications,
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


def test_get_tv_classifications_uses_screen():
    fake_screen = [
        {"symbol": "NYSE:BRK.B", "sector": "Finance", "industry": "Property/Casualty Insurance"},
        {"symbol": "NASDAQ:GOOGL", "sector": "Technology Services", "industry": "Internet Software/Services"},
    ]
    with mock.patch(
        "pytvtools_core.classifications.screen",
        return_value=(fake_screen, len(fake_screen)),
    ) as scr:
        rows = get_tv_classifications(exchanges=("NYSE",))
    scr.assert_called_once()
    assert rows == [
        {"symbol": "NYSE:BRK.B", "sector": "Finance", "industry": "Property/Casualty Insurance"},
        {"symbol": "NASDAQ:GOOGL", "sector": "Technology Services", "industry": "Internet Software/Services"},
    ]


def test_classification_rows_tags_taxonomy():
    _reset_cache()
    tv_rows = [
        {"symbol": "NYSE:A", "sector": "Finance", "industry": "Major Banks"},
    ]
    with mock.patch(
        "pytvtools_core.classifications.screen",
        return_value=(tv_rows, len(tv_rows)),
    ):
        rows = classification_rows(
            exchanges=("NYSE",), force_refetch=True
        )
    by_tax = {}
    for r in rows:
        by_tax.setdefault(r["taxonomy"], []).append(r)
    # GICS rows present (from static snapshot), TV rows tagged tv
    assert len(by_tax["tv"]) == 1
    tv = by_tax["tv"][0]
    assert tv["symbol"] == "NYSE:A"
    assert tv["taxonomy"] == "tv"
    assert tv["industry_group"] is None
    assert tv["sub_industry"] is None
    assert tv["security"] is None
    assert tv["refreshed_at"] is not None
    # every GICS row must have the full roll-up populated
    for r in by_tax["gics"]:
        assert r["taxonomy"] == "gics"
        assert r["industry_group"] and r["industry"] and r["sector"]
        assert r["industry_group"] is not None
    assert len(by_tax["gics"]) == len(_GICS_CONSTITUENTS_STATIC)
