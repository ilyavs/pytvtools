"""Tests for classifications.py — GICS + TradingView per-ticker taxonomy."""

from pytvtools_core.classifications import (
    _GICS_HIERARCHY,
    _GICS_CONSTITUENTS_STATIC,
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
