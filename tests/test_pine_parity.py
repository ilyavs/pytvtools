"""Tests for pine_parity.py — built-in vs reference comparison."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from pytvtools.pine_parity import (
    compare_pine_indicator,
    PineParityReport,
    PineMismatch,
    PineCompileError,
    PineEntityNotFoundError,
    PineIndicatorNotFoundError,
    get_pine_indicator_source,
)
from pytvtools.tv import TV


SAMPLE_BARS = [
    {"timestamp": 100 + i, "open": float(100 + i), "high": float(101 + i),
     "low": float(99 + i), "close": float(100 + i), "volume": 1000}
    for i in range(30)
]

SAMPLE_INDICATOR_DATA = {
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
        },
        {
            "name": "Plot 1",
            "values": [
                {"timestamp": 100 + i, "value": 50.0}
                for i in range(30)
            ],
        },
        {
            "name": "Plot 2",
            "values": [
                {"timestamp": 100 + i, "value": 60.0 if i < 15 else 55.0 + (i - 14) * 2.0}
                for i in range(30)
            ],
        },
    ],
}


@pytest.fixture
def mock_tv():
    tv = AsyncMock(spec=TV)
    tv.get_ohlcv = AsyncMock(return_value=SAMPLE_BARS)
    tv._get_study_ids = AsyncMock(return_value=[])
    tv._eval = AsyncMock(return_value=None)
    tv.pine_set_source = AsyncMock()
    tv.pine_compile = AsyncMock(return_value={"errors": []})
    tv.add_indicator = AsyncMock(return_value="builtin123")
    tv.remove_indicator = AsyncMock()
    tv.get_indicator_data = AsyncMock(return_value=SAMPLE_INDICATOR_DATA)
    tv.set_symbol = AsyncMock()
    tv.set_timeframe = AsyncMock()
    tv.wait_for_chart_ready = AsyncMock(return_value=True)
    return tv


class TestGetPineIndicatorSource:
    @pytest.mark.parametrize("name,expected_title", [
        ("rsi", "Custom RSI"),
        ("sma", "Custom SMA"),
        ("ema", "Custom EMA"),
        ("macd", "Custom MACD"),
        ("mfi", "Custom MFI"),
    ])
    def test_known_indicator(self, name, expected_title):
        source = get_pine_indicator_source(name)
        assert "//@version=5" in source
        assert expected_title in source

    def test_unknown_indicator_raises(self):
        with pytest.raises(PineIndicatorNotFoundError, match="nope"):
            get_pine_indicator_source("nope")


class TestComparePineIndicatorPythonMode:
    """Default mode: Python reference (no authentication needed)."""

    async def test_match(self, mock_tv):
        report = await compare_pine_indicator(
            mock_tv, "TEST", "1D", "rsi",
            max_bars=30, tolerance=1.0,
        )
        assert isinstance(report, PineParityReport)
        assert report.pine_name == "rsi"
        assert report.total_bars > 0
        assert report.source == "python"

    async def test_no_data_raises(self, mock_tv):
        mock_tv.get_ohlcv = AsyncMock(return_value=[])
        with pytest.raises(ValueError, match="No OHLCV data"):
            await compare_pine_indicator(mock_tv, "TEST", "1D", "rsi")

    async def test_unknown_pine_name_raises(self, mock_tv):
        with pytest.raises(PineIndicatorNotFoundError, match="unknown_pine"):
            await compare_pine_indicator(mock_tv, "TEST", "1D", "unknown_pine")


class TestComparePineIndicatorPineEditorMode:
    """Pine Editor mode: injects via UI (requires auth)."""

    async def test_match(self, mock_tv):
        mock_tv._get_study_ids = AsyncMock(side_effect=[
            [],
            ["custom123"],
        ])
        mock_tv.get_indicator_data = AsyncMock(return_value=SAMPLE_INDICATOR_DATA)
        report = await compare_pine_indicator(
            mock_tv, "TEST", "1D", "rsi",
            max_bars=30, tolerance=1.0,
            use_pine_editor=True,
        )
        assert isinstance(report, PineParityReport)
        assert report.pine_name == "rsi"
        assert report.total_bars > 0
        assert report.source == "pine_editor"

    @pytest.mark.parametrize("name,study_id", [
        ("rsi", "STD;RSI"),
        ("sma", "STD;SMA"),
        ("ema", "STD;EMA"),
        ("macd", "STD;MACD"),
        ("mfi", "STD;Money_Flow"),
    ])
    async def test_match_all_indicators(self, mock_tv, name, study_id):
        mock_tv._get_study_ids = AsyncMock(side_effect=[
            [],
            ["custom123"],
        ])
        mock_tv.get_indicator_data = AsyncMock(return_value=SAMPLE_INDICATOR_DATA)
        report = await compare_pine_indicator(
            mock_tv, "TEST", "1D", name,
            max_bars=30, tolerance=1.0,
            use_pine_editor=True,
        )
        assert isinstance(report, PineParityReport)
        assert report.pine_name == name
        assert report.total_bars > 0
        assert report.source == "pine_editor"

    async def test_entity_not_found_raises(self, mock_tv):
        mock_tv._get_study_ids = AsyncMock(return_value=[])
        with pytest.raises(PineEntityNotFoundError, match="No new study entity"):
            await compare_pine_indicator(
                mock_tv, "TEST", "1D", "rsi",
                use_pine_editor=True,
            )

    async def test_compile_error_raises(self, mock_tv):
        mock_tv.pine_compile = AsyncMock(
            return_value={"errors": ["Syntax error at line 10"]}
        )
        with pytest.raises(PineCompileError, match="Syntax error"):
            await compare_pine_indicator(
                mock_tv, "TEST", "1D", "rsi",
                use_pine_editor=True,
            )

    async def test_builtin_add_fail_raises(self, mock_tv):
        mock_tv.add_indicator = AsyncMock(return_value=None)
        with pytest.raises(RuntimeError, match="Failed to add"):
            await compare_pine_indicator(
                mock_tv, "TEST", "1D", "rsi",
                use_pine_editor=True,
            )

    async def test_inputs_applied_from_builtin(self, mock_tv):
        mock_tv._get_study_ids = AsyncMock(side_effect=[
            [],
            ["custom123"],
        ])
        # _eval is called: (1) read built-in inputs, (2) open Pine editor, (3) read custom inputs
        mock_tv._eval = AsyncMock(side_effect=[
            {"in_0": 21, "in_1": "close", "in_2": False},
            None,
            {"in_0": 20},
        ])
        await compare_pine_indicator(
            mock_tv, "TEST", "1D", "sma",
            max_bars=30, tolerance=1.0,
            use_pine_editor=True,
        )
        mock_tv.set_indicator_inputs.assert_called_once_with("custom123", {"in_0": 21})

    async def test_pine_set_source_called(self, mock_tv):
        mock_tv._get_study_ids = AsyncMock(side_effect=[
            [],
            ["custom123"],
        ])
        await compare_pine_indicator(
            mock_tv, "TEST", "1D", "rsi",
            max_bars=30, tolerance=1.0,
            use_pine_editor=True,
        )
        mock_tv.pine_set_source.assert_called_once()
        source = mock_tv.pine_set_source.call_args[0][0]
        assert "//@version=5" in source


class TestPineMismatch:
    def test_repr(self):
        m = PineMismatch(timestamp=100, reference_val=50.0, tv_val=55.0, delta=5.0)
        r = repr(m)
        assert "100" in r
        assert "50.0" in r
        assert "55.0" in r
        assert "5.0" in r


class TestPineParityReport:
    def test_match_rate(self):
        report = PineParityReport(
            symbol="TEST", timeframe="1D", pine_name="rsi",
            total_bars=100, matched=95, mismatches=[], tolerance=0.01,
        )
        assert report.match_rate == 95.0

    def test_match_rate_zero_bars(self):
        report = PineParityReport(
            symbol="TEST", timeframe="1D", pine_name="rsi",
            total_bars=0, matched=0, mismatches=[], tolerance=0.01,
        )
        assert report.match_rate == 0.0

    def test_summary(self):
        report = PineParityReport(
            symbol="TEST", timeframe="1D", pine_name="rsi",
            total_bars=100, matched=95, mismatches=[], tolerance=0.01,
        )
        s = report.summary()
        assert "TEST" in s
        assert "95.0%" in s
        assert "rsi" in s
        assert "python" in s

    def test_summary_pine_editor_source(self):
        report = PineParityReport(
            symbol="TEST", timeframe="1D", pine_name="rsi",
            total_bars=100, matched=95, mismatches=[], tolerance=0.01,
            source="pine_editor",
        )
        s = report.summary()
        assert "pine_editor" in s
