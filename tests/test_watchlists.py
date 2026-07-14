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

    def test_pink_list_watchlists_complete(self):
        """PINK_LIST_WATCHLISTS should contain all 7 new lists."""
        from pytvtools_core.watchlists import PINK_LIST_WATCHLISTS
        expected = {"METALS_MINERS", "INDEX_FUTURES", "INDEX_CFDS",
                     "INDEX_ETFS", "BONDS", "OIL", "URANIUM_STRATEGIC"}
        assert set(PINK_LIST_WATCHLISTS) == expected

    def test_watchlists_includes_legacy(self):
        assert "SPDR_SECTORS" in WATCHLISTS
        assert "SPDR_INDUSTRIES" in WATCHLISTS
        assert "SPDR_ALL" in WATCHLISTS
        assert "CRYPTO" in WATCHLISTS

    def test_metals_miners_spot_symbols(self):
        for sym in ("OANDA:XAUUSD", "TVC:GOLD", "OANDA:XAGUSD", "OANDA:XCUUSD"):
            assert sym in METALS_MINERS

    def test_metals_miners_miners(self):
        for sym in ("NEM", "FCX", "SCCO", "RIO", "BHP", "VALE"):
            assert sym in METALS_MINERS

    def test_index_futures_content(self):
        assert "CME_MINI:ES1!" in INDEX_FUTURES
        assert "CME_MINI:NQ1!" in INDEX_FUTURES
        assert "CBOT_MINI:YM1!" in INDEX_FUTURES
        assert "CME_MINI:RTY1!" in INDEX_FUTURES
        assert "EUREX:FDAX1!" in INDEX_FUTURES
        assert "EUREX:FESX1!" in INDEX_FUTURES

    def test_index_cfds_content(self):
        assert "SPCFD:SPX" in INDEX_CFDS
        assert "TVC:NDQ" in INDEX_CFDS
        assert "TVC:DJI" in INDEX_CFDS
        assert "TVC:RUT" in INDEX_CFDS
        assert "TVC:DAX" in INDEX_CFDS
        assert "TVC:NI225" in INDEX_CFDS

    def test_index_etfs_content(self):
        for sym in ("AMEX:SPY", "NASDAQ:QQQ", "AMEX:IWM", "AMEX:DIA",
                     "AMEX:VTI", "CBOE:MAGS", "NASDAQ:TLT"):
            assert sym in INDEX_ETFS

    def test_bonds_content(self):
        for sym in ("TVC:US10Y", "TVC:US02Y", "TVC:US03M", "TVC:TNX",
                     "CBOT:TN1!", "CBOT:ZT1!", "NASDAQ:TLT"):
            assert sym in BONDS

    def test_oil_content(self):
        for sym in ("TVC:USOIL", "TVC:UKOIL", "NYMEX:CL1!",
                     "OANDA:WTICOUSD", "OANDA:BCOUSD"):
            assert sym in OIL

    def test_uranium_strategic_content(self):
        for sym in ("AMEX:URA", "AMEX:URNM", "AMEX:REMX", "AMEX:SLX",
                     "CCJ", "DNN", "NXE", "LYC"):
            assert sym in URANIUM_STRATEGIC
