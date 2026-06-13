"""Tests for indicator_parity.py — Python vs TradingView comparison."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from pytvtools.indicator_parity import compare_indicator, ParityReport, Mismatch
from pytvtools.tv import TV


SAMPLE_BARS = [
    {"timestamp": 100 + i, "open": float(100 + i), "high": float(101 + i),
     "low": float(99 + i), "close": float(100 + i), "volume": 1000}
    for i in range(30)
]

SAMPLE_RSI_DATA = {
    "id": "abc123",
    "title": "RSI (14, close)",
    "count": 30,
    "plots": [
        {
            "name": "Plot 0",
            "values": [
                {"timestamp": 100 + i, "value": 60.0 if i < 15 else 55.0 + (i - 14) * 2.0}
                for i in range(30)
            ],
        }
    ],
}


@pytest.fixture
def mock_tv():
    tv = AsyncMock(spec=TV)
    tv.get_ohlcv = AsyncMock(return_value=SAMPLE_BARS)
    return tv


class TestCompareIndicator:
    async def test_match(self, mock_tv):
        mock_tv.add_indicator = AsyncMock(return_value="abc123")
        mock_tv.get_indicator_data = AsyncMock(return_value=SAMPLE_RSI_DATA)
        mock_tv.set_symbol = AsyncMock()
        mock_tv.set_timeframe = AsyncMock()

        report = await compare_indicator(
            mock_tv, "TEST", "1D", "STD;RSI",
            max_bars=30, tolerance=1.0,
        )
        assert isinstance(report, ParityReport)
        assert report.indicator == "STD;RSI"
        assert report.total_bars > 0

    async def test_no_data_raises(self, mock_tv):
        mock_tv.get_ohlcv = AsyncMock(return_value=[])
        mock_tv.set_symbol = AsyncMock()
        mock_tv.set_timeframe = AsyncMock()

        with pytest.raises(ValueError, match="No OHLCV data"):
            await compare_indicator(mock_tv, "TEST", "1D", "STD;RSI")

    async def test_unknown_indicator_raises(self, mock_tv):
        with pytest.raises(ValueError, match="No Python implementation"):
            await compare_indicator(mock_tv, "TEST", "1D", "STD;UNKNOWN_STUDY")

    async def test_sma_detected(self, mock_tv):
        mock_tv.set_symbol = AsyncMock()
        mock_tv.set_timeframe = AsyncMock()
        mock_tv.get_ohlcv = AsyncMock(return_value=SAMPLE_BARS)
        mock_tv.add_indicator = AsyncMock(return_value="abc123")
        mock_tv.get_indicator_data = AsyncMock(return_value=SAMPLE_RSI_DATA)
        report = await compare_indicator(
            mock_tv, "TEST", "1D", "STD;SMA",
            max_bars=30, tolerance=1.0,
        )
        assert report.indicator == "STD;SMA"

    async def test_ema_detected(self, mock_tv):
        mock_tv.set_symbol = AsyncMock()
        mock_tv.set_timeframe = AsyncMock()
        mock_tv.get_ohlcv = AsyncMock(return_value=SAMPLE_BARS)
        mock_tv.add_indicator = AsyncMock(return_value="abc123")
        mock_tv.get_indicator_data = AsyncMock(return_value=SAMPLE_RSI_DATA)
        report = await compare_indicator(
            mock_tv, "TEST", "1D", "STD;EMA",
            max_bars=30, tolerance=1.0,
        )
        assert report.indicator == "STD;EMA"

    async def test_entity_id_provided(self, mock_tv):
        mock_tv.add_indicator = AsyncMock(return_value="abc123")
        mock_tv.get_indicator_data = AsyncMock(return_value=SAMPLE_RSI_DATA)
        mock_tv.set_symbol = AsyncMock()
        mock_tv.set_timeframe = AsyncMock()

        report = await compare_indicator(
            mock_tv, "TEST", "1D", "STD;RSI",
            entity_id="my_id", max_bars=30, tolerance=1.0,
        )
        # Should NOT call add_indicator when entity_id is provided
        mock_tv.add_indicator.assert_not_called()
        assert isinstance(report, ParityReport)


class TestMismatch:
    def test_mismatch_repr(self):
        m = Mismatch(timestamp=100, py_val=50.0, tv_val=55.0, delta=5.0)
        r = repr(m)
        assert "100" in r
        assert "50.0" in r
        assert "55.0" in r


class TestParityReport:
    def test_match_rate(self):
        report = ParityReport(
            symbol="TEST", timeframe="1D", indicator="RSI",
            total_bars=100, matched=95, mismatches=[], tolerance=0.01,
        )
        assert report.match_rate == 95.0

    def test_match_rate_zero_bars(self):
        report = ParityReport(
            symbol="TEST", timeframe="1D", indicator="RSI",
            total_bars=0, matched=0, mismatches=[], tolerance=0.01,
        )
        assert report.match_rate == 0.0

    def test_summary(self):
        report = ParityReport(
            symbol="TEST", timeframe="1D", indicator="RSI",
            total_bars=100, matched=95, mismatches=[], tolerance=0.01,
        )
        s = report.summary()
        assert "TEST" in s
        assert "95.0%" in s
