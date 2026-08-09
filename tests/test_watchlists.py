"""Tests for watchlists.py — predefined watchlist library."""

import io
import json
from unittest import mock

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
    screen,
    get_watchlist,
    us_stock_rows,
    get_us_stocks,
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
        assert len(INDEX_CFDS) == 10

    def test_index_etfs_len(self):
        assert len(INDEX_ETFS) == 6

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
        assert "TVC:VIX" in INDEX_CFDS

    def test_index_etfs_content(self):
        for sym in ("AMEX:SPY", "NASDAQ:QQQ", "AMEX:IWM", "AMEX:DIA",
                     "AMEX:VTI", "CBOE:MAGS"):
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


from pytvtools_core.watchlists import registry_rows, Watchlist


class TestRegistryRows:
    def test_includes_static_watchlists(self):
        rows = registry_rows(sp500=Watchlist("S&P 500", ("FAKESP",)))
        syms = {r["symbol"] for r in rows}
        assert "XLK" in syms
        assert "TVC:US10Y" in syms
        assert "AMEX:URA" in syms

    def test_static_rows_use_watchlist_source(self):
        rows = registry_rows(sp500=Watchlist("S&P 500", ("FAKESP",)))
        xlk = [r for r in rows if r["symbol"] == "XLK" and r["watchlist"] == "SPDR_SECTORS"]
        assert len(xlk) == 1
        assert xlk[0]["watchlist"] == "SPDR_SECTORS"
        assert xlk[0]["source"] == "watchlist"

    def test_sp500_rows_use_sp500_source(self):
        rows = registry_rows(sp500=Watchlist("S&P 500", ("AAA", "CCC")))
        sp = [r for r in rows if r["source"] == "sp500"]
        assert {r["symbol"] for r in sp} == {"AAA", "CCC"}
        assert all(r["watchlist"] == "SP500" for r in sp)

    def test_symbol_in_multiple_watchlists_has_multiple_rows(self):
        rows = registry_rows(sp500=Watchlist("S&P 500", ("SLX",)))
        slx = [r for r in rows if r["symbol"] == "SLX"]
        assert {r["watchlist"] for r in slx} == {
            "SPDR_INDUSTRIES", "SPDR_ALL", "SP500"}
        assert len(slx) >= 3

    def test_returns_plain_dicts(self):
        rows = registry_rows(sp500=Watchlist("S&P 500", ("FAKESP",)))
        assert set(rows[0]) == {"symbol", "watchlist", "source"}


class TestScreen:
    """screen() queries TradingView's scanner API and returns rows + total."""

    URL = "https://scanner.tradingview.com/america/scan"

    @staticmethod
    def _fake_urlopen(responses):
        seq = iter(responses)

        def _open(req, timeout=None):
            return io.BytesIO(json.dumps(next(seq)).encode())

        return _open

    def test_returns_rows_and_total(self):
        resp = {
            "totalCount": 2,
            "data": [
                {"s": "NYSE:A", "d": ["A", 145.97]},
                {"s": "NYSE:AA", "d": ["AA", 50.17]},
            ],
        }
        with mock.patch("urllib.request.urlopen", side_effect=self._fake_urlopen([resp])):
            rows, total = screen(columns=("name", "close"))
        assert total == 2
        assert rows == [
            {"symbol": "NYSE:A", "name": "A", "close": 145.97},
            {"symbol": "NYSE:AA", "name": "AA", "close": 50.17},
        ]

    def test_sends_exchange_filter_and_types(self):
        seen = {}

        def _open(req, timeout=None):
            seen["url"] = req.full_url
            seen["data"] = json.loads(req.data.decode())
            return io.BytesIO(json.dumps({"totalCount": 0, "data": []}).encode())

        with mock.patch("urllib.request.urlopen", side_effect=_open):
            screen(exchange="NYSE")
        assert seen["url"] == TestScreen.URL
        assert seen["data"]["symbols"] == {"query": {"types": ["stock"]}}
        assert seen["data"]["filter"] == [
            {"left": "exchange", "operation": "equal", "right": "NYSE"}
        ]

    def test_paginates_until_all_fetched(self):
        dataset = ["A", "AB", "ABT"]
        seen_ranges = []

        def _open(req, timeout=None):
            body = json.loads(req.data.decode())
            start, end = body["range"]
            seen_ranges.append([start, end])
            page = [
                {"s": f"NYSE:{s}", "d": [s]}
                for s in dataset[start:end]
            ]
            return io.BytesIO(
                json.dumps({"totalCount": len(dataset), "data": page}).encode()
            )

        with mock.patch("urllib.request.urlopen", side_effect=_open):
            rows, total = screen(columns=("name",), page_size=2)
        assert [r["symbol"] for r in rows] == ["NYSE:A", "NYSE:AB", "NYSE:ABT"]
        assert total == 3
        assert seen_ranges == [[0, 2], [2, 4]]


class TestUSStocks:
    @staticmethod
    def _fake_urlopen(responses):
        seq = iter(responses)

        def _open(req, timeout=None):
            return io.BytesIO(json.dumps(next(seq)).encode())

        return _open

    def test_us_stock_rows_unions_exchanges(self):
        responses = [
            {"totalCount": 2, "data": [{"s": "NYSE:A", "d": ["A"]},
                                      {"s": "NYSE:B", "d": ["B"]}]},
            {"totalCount": 1, "data": [{"s": "NASDAQ:COST", "d": ["COST"]}]},
            {"totalCount": 0, "data": []},
        ]
        with mock.patch("urllib.request.urlopen",
                        side_effect=self._fake_urlopen(responses)):
            rows = us_stock_rows(exchanges=("NYSE", "NASDAQ", "AMEX"))
        assert [r["symbol"] for r in rows] == ["NYSE:A", "NYSE:B", "NASDAQ:COST"]
        for r in rows:
            assert set(r) == {"symbol", "watchlist", "source"}
            assert r["watchlist"] == "US_STOCKS"
            assert r["source"] == "screen"

    def test_us_stock_rows_sends_exchange_filter_per_call(self):
        seen = []

        def _open(req, timeout=None):
            body = json.loads(req.data.decode())
            seen.append(body["filter"])
            return io.BytesIO(json.dumps({"totalCount": 1, "data": [
                {"s": "NASDAQ:T", "d": ["T"]}]}).encode())

        with mock.patch("urllib.request.urlopen", side_effect=_open):
            rows = us_stock_rows(exchanges=("NASDAQ",))
        assert seen == [[{"left": "exchange", "operation": "equal",
                          "right": "NASDAQ"}]]
        assert rows[0]["symbol"] == "NASDAQ:T"

    def test_get_us_stocks_returns_prefixed_watchlist(self):
        # get_us_stocks() calls us_stock_rows() -> one scanner call per exchange
        responses = [
            {"totalCount": 1, "data": [{"s": "NYSE:XOM", "d": ["XOM"]}]},
            {"totalCount": 0, "data": []},  # NASDAQ
            {"totalCount": 0, "data": []},  # AMEX
        ]
        with mock.patch("urllib.request.urlopen",
                        side_effect=self._fake_urlopen(responses)):
            wl = get_us_stocks()
        assert wl.name == "US Stocks"
        assert wl.symbols == ("NYSE:XOM",)
