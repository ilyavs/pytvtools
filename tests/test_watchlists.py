"""Tests for watchlists.py — predefined watchlist library."""

import pytest

from pytvtools_core.watchlists import (
    Watchlist,
    SPDR_SECTORS,
    SPDR_INDUSTRIES,
    SPDR_ALL,
)


class TestWatchlist:
    def test_repr(self):
        assert "SPDR" in repr(SPDR_SECTORS)

    def test_len(self):
        assert len(SPDR_SECTORS) == 11
        assert len(SPDR_INDUSTRIES) == 19
        assert len(SPDR_ALL) == 30

    def test_iter(self):
        assert list(SPDR_SECTORS)[0] == "XLK"
        assert list(SPDR_SECTORS)[-1] == "XLU"

    def test_getitem(self):
        assert SPDR_SECTORS[0] == "XLK"
        assert SPDR_SECTORS[-1] == "XLU"

    def test_contains(self):
        assert "XLK" in SPDR_SECTORS
        assert "XBI" not in SPDR_SECTORS
        assert "XBI" in SPDR_INDUSTRIES
        assert "XLK" in SPDR_ALL
        assert "XBI" in SPDR_ALL

    def test_tuple_immutable(self):
        assert isinstance(SPDR_SECTORS.symbols, tuple)
        assert isinstance(SPDR_INDUSTRIES.symbols, tuple)

    def test_spdr_all_contains_all(self):
        expected = set(SPDR_SECTORS.symbols) | set(SPDR_INDUSTRIES.symbols)
        assert set(SPDR_ALL.symbols) == expected
