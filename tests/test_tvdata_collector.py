"""Tests for TVDataCollector — CDP-free OHLCV collection with export."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from pytvtools.collector import CollectResult, TVDataCollector, TVDataCollectorConfig


SAMPLE_DATA = {
    "SP:SPX": {"bars": 100, "high": 5000.0, "low": 4000.0, "open": 4500.0, "close": 4800.0, "avg_volume": 2000000000, "range": 1000.0},
    "COINBASE:BTCUSD": {"bars": 100, "high": 70000.0, "low": 50000.0, "open": 60000.0, "close": 65000.0, "avg_volume": 30000, "range": 20000.0},
}

ERROR_DATA = {
    "SP:SPX": SAMPLE_DATA["SP:SPX"],
    "COINBASE:BTCUSD": {"error": "rate limited"},
}


# ---------------------------------------------------------------------------
# TVDataCollectorConfig
# ---------------------------------------------------------------------------


class TestTVDataCollectorConfig:
    def test_defaults(self):
        cfg = TVDataCollectorConfig(symbols=["A"], timeframes=["1D"])
        assert cfg.bars_count == 500
        assert cfg.max_concurrent == 5

    def test_custom(self):
        cfg = TVDataCollectorConfig(symbols=["A"], timeframes=["1D"], bars_count=100, max_concurrent=10)
        assert cfg.bars_count == 100
        assert cfg.max_concurrent == 10


# ---------------------------------------------------------------------------
# TVDataCollector.run
# ---------------------------------------------------------------------------


class TestTVDataCollectorRun:
    @patch("pytvtools.collector.TVData")
    async def test_basic_collection(self, mock_tvdata_cls):
        mock_instance = AsyncMock()
        mock_instance.get_ohlcv_multi = AsyncMock(return_value=SAMPLE_DATA)
        mock_tvdata_cls.return_value.__aenter__.return_value = mock_instance

        collector = TVDataCollector(symbols=["SP:SPX", "COINBASE:BTCUSD"], timeframes=["1D"], bars_count=100)
        result = await collector.run()

        assert isinstance(result, CollectResult)
        assert result.symbols_total == 2
        assert result.symbols_failed == []
        assert len(result.records) == 2

        spx = next(r for r in result.records if r["symbol"] == "SP:SPX")
        assert spx["timeframe"] == "1D"
        assert spx["ohlcv_close"] == 4800.0
        assert spx["ohlcv_bars"] == 100

    @patch("pytvtools.collector.TVData")
    async def test_multiple_timeframes(self, mock_tvdata_cls):
        mock_instance = AsyncMock()

        async def multi_side_effect(symbols, interval, bars_count, *, summary, max_concurrent):
            return {sym: dict(SAMPLE_DATA[sym]) for sym in symbols}

        mock_instance.get_ohlcv_multi = AsyncMock(side_effect=multi_side_effect)
        mock_tvdata_cls.return_value.__aenter__.return_value = mock_instance

        collector = TVDataCollector(symbols=["SP:SPX", "COINBASE:BTCUSD"], timeframes=["1D", "60"], bars_count=100)
        result = await collector.run()

        assert len(result.records) == 4  # 2 symbols × 2 TFs
        assert mock_instance.get_ohlcv_multi.call_count == 2

    @patch("pytvtools.collector.TVData")
    async def test_partial_failures(self, mock_tvdata_cls):
        mock_instance = AsyncMock()
        mock_instance.get_ohlcv_multi = AsyncMock(return_value=ERROR_DATA)
        mock_tvdata_cls.return_value.__aenter__.return_value = mock_instance

        collector = TVDataCollector(symbols=["SP:SPX", "COINBASE:BTCUSD"], timeframes=["1D"], bars_count=100)
        result = await collector.run()

        assert len(result.records) == 1
        assert result.records[0]["symbol"] == "SP:SPX"

    @patch("pytvtools.collector.TVData")
    async def test_all_failures(self, mock_tvdata_cls):
        mock_instance = AsyncMock()
        mock_instance.get_ohlcv_multi = AsyncMock(return_value={"A": {"error": "fail"}})
        mock_tvdata_cls.return_value.__aenter__.return_value = mock_instance

        collector = TVDataCollector(symbols=["A"], timeframes=["1D"], bars_count=100)
        result = await collector.run()

        assert len(result.records) == 0
        assert result.symbols_failed == ["A"]

    @patch("pytvtools.collector.TVData")
    async def test_scan_ts(self, mock_tvdata_cls):
        mock_instance = AsyncMock()
        mock_instance.get_ohlcv_multi = AsyncMock(return_value=SAMPLE_DATA)
        mock_tvdata_cls.return_value.__aenter__.return_value = mock_instance

        collector = TVDataCollector(symbols=["SP:SPX"], timeframes=["1D"], bars_count=100)
        result = await collector.run()

        assert result.records[0]["scan_ts"] is not None

    @patch("pytvtools.collector.TVData")
    async def test_custom_bars_count(self, mock_tvdata_cls):
        mock_instance = AsyncMock()
        mock_instance.get_ohlcv_multi = AsyncMock(return_value=SAMPLE_DATA)
        mock_tvdata_cls.return_value.__aenter__.return_value = mock_instance

        collector = TVDataCollector(symbols=["SP:SPX"], timeframes=["1D"], bars_count=2000)
        result = await collector.run()

        mock_instance.get_ohlcv_multi.assert_awaited_once_with(
            ["SP:SPX"], "1D", 2000, summary=True, max_concurrent=5,
        )


# ---------------------------------------------------------------------------
# TVDataCollector.export_json
# ---------------------------------------------------------------------------


class TestTVDataCollectorExportJson:
    @patch("pytvtools.collector.TVData")
    async def test_export_json(self, mock_tvdata_cls, tmp_path):
        mock_instance = AsyncMock()
        mock_instance.get_ohlcv_multi = AsyncMock(return_value=SAMPLE_DATA)
        mock_tvdata_cls.return_value.__aenter__.return_value = mock_instance

        collector = TVDataCollector(symbols=list(SAMPLE_DATA.keys()), timeframes=["1D"], bars_count=100)
        await collector.run()

        path = tmp_path / "out.json"
        result_path = collector.export_json(path, overwrite=True)
        assert result_path == path
        assert path.exists()

        lines = path.read_text().strip().split("\n")
        assert len(lines) == len(SAMPLE_DATA)

    @patch("pytvtools.collector.TVData")
    async def test_export_json_no_run(self, mock_tvdata_cls):
        collector = TVDataCollector(symbols=["A"], timeframes=["1D"])
        with pytest.raises(RuntimeError, match="run"):
            collector.export_json("out.json")

    @patch("pytvtools.collector.TVData")
    async def test_export_json_file_exists(self, mock_tvdata_cls, tmp_path):
        mock_instance = AsyncMock()
        mock_instance.get_ohlcv_multi = AsyncMock(return_value=SAMPLE_DATA)
        mock_tvdata_cls.return_value.__aenter__.return_value = mock_instance

        collector = TVDataCollector(symbols=list(SAMPLE_DATA.keys()), timeframes=["1D"], bars_count=100)
        await collector.run()

        path = tmp_path / "out.json"
        path.write_text("existing")
        with pytest.raises(FileExistsError):
            collector.export_json(path)


# ---------------------------------------------------------------------------
# TVDataCollector.export_parquet (requires pyarrow via [full] extra)
# ---------------------------------------------------------------------------


class TestTVDataCollectorExportParquet:
    @patch("pytvtools.collector.TVData")
    async def test_export_parquet(self, mock_tvdata_cls, tmp_path):
        mock_instance = AsyncMock()
        mock_instance.get_ohlcv_multi = AsyncMock(return_value=SAMPLE_DATA)
        mock_tvdata_cls.return_value.__aenter__.return_value = mock_instance

        collector = TVDataCollector(symbols=["SP:SPX"], timeframes=["1D"], bars_count=100)
        await collector.run()

        path = tmp_path / "out.parquet"
        result_path = collector.export_parquet(path, overwrite=True)
        assert result_path == path
        assert path.exists()
        # Parquet is binary — just verify it's non-empty
        assert path.stat().st_size > 0

    @patch("pytvtools.collector.TVData")
    async def test_export_parquet_auto_extension(self, mock_tvdata_cls, tmp_path):
        mock_instance = AsyncMock()
        mock_instance.get_ohlcv_multi = AsyncMock(return_value=SAMPLE_DATA)
        mock_tvdata_cls.return_value.__aenter__.return_value = mock_instance

        collector = TVDataCollector(symbols=["SP:SPX"], timeframes=["1D"], bars_count=100)
        await collector.run()

        path = tmp_path / "out"
        result_path = collector.export_parquet(path, overwrite=True)
        assert str(result_path).endswith(".parquet")

    @patch("pytvtools.collector.TVData")
    async def test_export_parquet_no_run(self, mock_tvdata_cls):
        collector = TVDataCollector(symbols=["A"], timeframes=["1D"])
        with pytest.raises(RuntimeError, match="run"):
            collector.export_parquet("out.parquet")

    @patch("pytvtools.collector.TVData")
    async def test_export_parquet_file_exists(self, mock_tvdata_cls, tmp_path):
        mock_instance = AsyncMock()
        mock_instance.get_ohlcv_multi = AsyncMock(return_value=SAMPLE_DATA)
        mock_tvdata_cls.return_value.__aenter__.return_value = mock_instance

        collector = TVDataCollector(symbols=["SP:SPX"], timeframes=["1D"], bars_count=100)
        await collector.run()

        path = tmp_path / "out.parquet"
        path.write_text("existing")
        with pytest.raises(FileExistsError):
            collector.export_parquet(path)

    @patch("pytvtools.collector.TVData")
    async def test_export_parquet_empty(self, mock_tvdata_cls, tmp_path):
        mock_instance = AsyncMock()
        mock_instance.get_ohlcv_multi = AsyncMock(return_value={"A": {"error": "fail"}})
        mock_tvdata_cls.return_value.__aenter__.return_value = mock_instance

        collector = TVDataCollector(symbols=["A"], timeframes=["1D"], bars_count=100)
        await collector.run()

        path = tmp_path / "empty.parquet"
        result_path = collector.export_parquet(path, overwrite=True)
        assert result_path.exists()
