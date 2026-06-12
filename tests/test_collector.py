"""Tests for collector.py — multi-symbol data collection with parquet export.

Mocks TV.batch() so no real Chrome/TradingView is needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from pytvtools.collector import Collector, CollectorConfig, CollectResult
from pytvtools.tv import TV

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_tv():
    tv = AsyncMock(spec=TV)
    return tv


SAMPLE_OHLCV = {
    "NASDAQ:AAPL": {
        "1D": {"count": 100, "high": 200.0, "low": 150.0, "open": 160.0, "close": 190.0, "avg_volume": 50000000, "range": 50.0},
    },
    "NASDAQ:MSFT": {
        "1D": {"count": 100, "high": 400.0, "low": 350.0, "open": 360.0, "close": 390.0, "avg_volume": 30000000, "range": 50.0},
        "60": {"count": 50, "high": 395.0, "low": 355.0, "open": 360.0, "close": 390.0, "avg_volume": 5000000, "range": 40.0},
    },
}

SAMPLE_STUDIES = {
    "NASDAQ:AAPL": {
        "1D": {"Relative Strength Index": {"title": "RSI (14, close)", "values": [{"timestamp": 100, "value": 55.0}]}},
    },
    "NASDAQ:MSFT": {
        "1D": {"Relative Strength Index": {"title": "RSI (14, close)", "values": [{"timestamp": 100, "value": 45.0}]}},
        "60": {"Relative Strength Index": {"title": "RSI (14, close)", "values": [{"timestamp": 100, "value": 48.0}]}},
    },
}

SAMPLE_ALL = {
    "NASDAQ:AAPL": {
        "1D": {"ohlcv": SAMPLE_OHLCV["NASDAQ:AAPL"]["1D"], "studies": SAMPLE_STUDIES["NASDAQ:AAPL"]["1D"]},
    },
    "NASDAQ:MSFT": {
        "1D": {"ohlcv": SAMPLE_OHLCV["NASDAQ:MSFT"]["1D"], "studies": SAMPLE_STUDIES["NASDAQ:MSFT"]["1D"]},
        "60": {"ohlcv": SAMPLE_OHLCV["NASDAQ:MSFT"]["60"], "studies": SAMPLE_STUDIES["NASDAQ:MSFT"]["60"]},
    },
}


# ---------------------------------------------------------------------------
# CollectorConfig
# ---------------------------------------------------------------------------


class TestCollectorConfig:
    def test_default_actions(self):
        c = CollectorConfig(symbols=["A"], timeframes=["1D"])
        assert c.actions == ["ohlcv", "studies"]

    def test_custom_actions(self):
        c = CollectorConfig(symbols=["A"], timeframes=["1D"], actions=["ohlcv"])
        assert c.actions == ["ohlcv"]

    def test_invalid_action(self):
        with pytest.raises(ValueError, match="Unknown action"):
            CollectorConfig(symbols=["A"], timeframes=["1D"], actions=["baloney"])


# ---------------------------------------------------------------------------
# Collector.run
# ---------------------------------------------------------------------------


class TestCollectorRun:
    async def test_ohlcv_only(self, mock_tv):
        mock_tv.batch = AsyncMock(return_value=SAMPLE_OHLCV)
        config = CollectorConfig(
            symbols=["NASDAQ:AAPL", "NASDAQ:MSFT"],
            timeframes=["1D", "60"],
            actions=["ohlcv"],
        )
        collector = Collector(config)
        result = await collector.run(mock_tv)

        assert isinstance(result, CollectResult)
        assert result.symbols_total == 2
        assert len(result.records) == 3  # AAPL(1D) + MSFT(1D,60)

        mock_tv.batch.assert_awaited_once_with(
            ["NASDAQ:AAPL", "NASDAQ:MSFT"],
            ["1D", "60"],
            "ohlcv",
            max_bars=500,
        )

    async def test_actions_merge(self, mock_tv):
        # Collector uses single-pass "all" when both ohlcv + studies configured
        mock_tv.batch = AsyncMock(return_value=SAMPLE_ALL)
        config = CollectorConfig(
            symbols=["NASDAQ:AAPL", "NASDAQ:MSFT"],
            timeframes=["1D", "60"],
            actions=["ohlcv", "studies"],
        )
        collector = Collector(config)
        result = await collector.run(mock_tv)

        assert len(result.records) == 3
        mock_tv.batch.assert_awaited_once_with(
            ["NASDAQ:AAPL", "NASDAQ:MSFT"],
            ["1D", "60"],
            "all",
            max_bars=500,
        )

        msft_1d = next(r for r in result.records if r["symbol"] == "NASDAQ:MSFT" and r["timeframe"] == "1D")
        assert msft_1d["ohlcv_close"] == 390.0
        assert msft_1d["st_Relative Strength Index"] == 45.0

        aapl_1d = next(r for r in result.records if r["symbol"] == "NASDAQ:AAPL")
        assert aapl_1d["ohlcv_close"] == 190.0
        assert aapl_1d["st_Relative Strength Index"] == 55.0

    async def test_scan_ts_populated(self, mock_tv):
        mock_tv.batch = AsyncMock(return_value=SAMPLE_OHLCV)
        collector = Collector(CollectorConfig(symbols=["A"], timeframes=["1D"], actions=["ohlcv"]))
        result = await collector.run(mock_tv)
        assert result.records[0]["scan_ts"] is not None

    async def test_no_records(self, mock_tv):
        mock_tv.batch = AsyncMock(return_value={"A": {"1D": None}})
        collector = Collector(CollectorConfig(symbols=["A"], timeframes=["1D"], actions=["ohlcv"]))
        result = await collector.run(mock_tv)
        assert len(result.records) == 0

    async def test_symbols_failed(self, mock_tv):
        mock_tv.batch = AsyncMock(return_value={"A": {"1D": None, "60": None}})
        collector = Collector(CollectorConfig(symbols=["A"], timeframes=["1D", "60"], actions=["ohlcv"]))
        result = await collector.run(mock_tv)
        assert result.symbols_failed == ["A"]

    async def test_symbols_partial_fail(self, mock_tv):
        data = {"A": {"1D": SAMPLE_OHLCV["NASDAQ:AAPL"]["1D"], "60": None}}
        mock_tv.batch = AsyncMock(return_value=data)
        collector = Collector(CollectorConfig(symbols=["A"], timeframes=["1D", "60"], actions=["ohlcv"]))
        result = await collector.run(mock_tv)
        assert result.symbols_failed == []
        assert len(result.records) == 1
        assert result.records[0]["timeframe"] == "1D"

    async def test_custom_max_bars(self, mock_tv):
        data = {"A": {"1D": SAMPLE_OHLCV["NASDAQ:AAPL"]["1D"]}}
        mock_tv.batch = AsyncMock(return_value=data)
        collector = Collector(CollectorConfig(symbols=["A"], timeframes=["1D"], actions=["ohlcv"], max_bars=1000))
        await collector.run(mock_tv)
        mock_tv.batch.assert_awaited_once_with(
            ["A"], ["1D"], "ohlcv", max_bars=1000,
        )


# ---------------------------------------------------------------------------
# Collector.export_json (no parquet dependency needed)
# ---------------------------------------------------------------------------


class TestExportJson:
    async def test_export_json(self, mock_tv, tmp_path):
        mock_tv.batch = AsyncMock(return_value=SAMPLE_OHLCV)
        config = CollectorConfig(
            symbols=list(SAMPLE_OHLCV.keys()),
            timeframes=["1D", "60"],
            actions=["ohlcv"],
        )
        collector = Collector(config)
        result = await collector.run(mock_tv)

        path = tmp_path / "out.json"
        result_path = collector.export_json(path, overwrite=True)
        assert result_path == path
        assert path.exists()

        lines = path.read_text().strip().split("\n")
        assert len(lines) == len(result.records)

    async def test_export_json_no_run(self, mock_tv):
        collector = Collector(CollectorConfig(symbols=["A"], timeframes=["1D"]))
        with pytest.raises(RuntimeError, match="run"):
            collector.export_json("out.json")

    async def test_export_json_file_exists(self, mock_tv, tmp_path):
        mock_tv.batch = AsyncMock(return_value=SAMPLE_OHLCV)
        collector = Collector(CollectorConfig(symbols=["NASDAQ:AAPL"], timeframes=["1D"], actions=["ohlcv"]))
        await collector.run(mock_tv)

        path = tmp_path / "out.json"
        path.write_text("existing")
        with pytest.raises(FileExistsError):
            collector.export_json(path)
