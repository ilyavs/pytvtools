"""Tests for watchlists.py — predefined watchlist library."""

import pytest

from pytvtools_core.watchlists import (
    Watchlist,
    SPDR_SECTORS,
    SPDR_INDUSTRIES,
    SPDR_ALL,
    METALS_MINERS,
    INDEX_FUTURES,
    INDEX_CFDS,
    INDEX_ETFS,
    BONDS,
    OIL,
    URANIUM_STRATEGIC,
    WATCHLISTS,
    get_watchlist,
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


class TestNewWatchlists:
    def test_metals_miners_len(self):
        assert len(METALS_MINERS) == 31

    def test_index_futures_len(self):
        assert len(INDEX_FUTURES) == 6

    def test_index_cfds_len(self):
        assert len(INDEX_CFDS) == 9

    def test_index_etfs_len(self):
        assert len(INDEX_ETFS) == 7

    def test_bonds_len(self):
        assert len(BONDS) == 7

    def test_oil_len(self):
        assert len(OIL) == 5

    def test_uranium_strategic_len(self):
        assert len(URANIUM_STRATEGIC) == 22

    def test_watchlists_registry(self):
        for name in ("METALS_MINERS", "INDEX_FUTURES", "INDEX_CFDS",
                     "INDEX_ETFS", "BONDS", "OIL", "URANIUM_STRATEGIC"):
            assert name in WATCHLISTS
            assert get_watchlist(name) is WATCHLISTS[name]

    def test_get_watchlist_unknown(self):
        with pytest.raises(KeyError):
            get_watchlist("NONEXISTENT")
