"""Tests for tvdata.py — direct WebSocket OHLCV fetcher.

All tests mock websockets.connect so no real TradingView connection is needed.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pytvtools_core.tvdata import TVData, _session_id


def _tv_frame(msg_type: str, params: list) -> str:
    """Build a TradingView WebSocket frame string."""
    payload = json.dumps({"m": msg_type, "p": params}, separators=(",", ":"))
    return f"~m~{len(payload)}~m~{payload}"


def _heartbeat_frame(n: int = 42) -> str:
    return f"~m~5~m~~h~{n}"


def _du_frame(
    session: str,
    bars: list[tuple],
    series_id: str = "sds_1",
) -> str:
    """Build a TradingView 'du' data-update frame with bar data.

    Each bar: (timestamp, open, high, low, close, volume)
    """
    entries = [{"i": idx, "v": list(bar)} for idx, bar in enumerate(bars)]
    data = {
        series_id: {
            "s": entries,
            "ns": {"d": "", "indexes": "s"},
            "t": "s",
        }
    }
    return _tv_frame("du", [session, data])


def _series_completed(session: str, series_id: str = "sds_1") -> str:
    return _tv_frame("series_completed", [session, series_id])


def _symbol_error(session: str, symbol: str, msg: str = "Unknown symbol") -> str:
    return _tv_frame("symbol_error", [session, f"sds_sym_1", msg])


def _series_loading(session: str) -> str:
    return _tv_frame("series_loading", [session, "sds_1"])


@pytest.fixture
async def mock_tvdata():
    """TVData with mocked WebSocket connection."""
    ws = AsyncMock()
    ws.send = AsyncMock()
    ws.recv = AsyncMock()
    ws.close = AsyncMock()

    td = TVData()
    td._ws = ws  # skip actual connection, just set ws
    yield td, ws
    await td.__aexit__(None, None, None)


class TestTVData:
    async def test_get_ohlcv_basic(self, mock_tvdata):
        """Fetch bars and verify parsing."""
        td, ws = mock_tvdata
        session = _session_id()

        # Simulate the protocol flow: heartbeat, series_loading, du, series_completed
        bars = [
            (1704067200, 190.0, 191.0, 189.5, 190.5, 1000000),
            (1704153600, 190.5, 192.0, 190.0, 191.5, 1200000),
        ]
        ws.recv.side_effect = [
            _heartbeat_frame(),
            _series_loading(session),
            _du_frame(session, bars),
            _series_completed(session),
        ]

        result = await td.get_ohlcv("NASDAQ:AAPL", "1D", 2)

        assert len(result) == 2
        assert result[0]["timestamp"] == 1704067200
        assert result[0]["open"] == 190.0
        assert result[0]["close"] == 190.5
        assert result[0]["volume"] == 1000000
        assert result[1]["timestamp"] == 1704153600
        assert result[1]["high"] == 192.0
        assert result[1]["close"] == 191.5

    async def test_get_ohlcv_summary(self, mock_tvdata):
        """Summary mode returns aggregated stats."""
        td, ws = mock_tvdata
        session = _session_id()

        bars = [
            (1704067200, 190.0, 192.0, 189.0, 191.0, 1000000),
            (1704153600, 191.0, 193.0, 190.0, 192.0, 2000000),
            (1704240000, 192.0, 195.0, 191.0, 194.0, 1500000),
        ]
        ws.recv.side_effect = [
            _series_loading(session),
            _du_frame(session, bars),
            _series_completed(session),
        ]

        result = await td.get_ohlcv("NASDAQ:AAPL", "1D", 3, summary=True)

        assert isinstance(result, dict)
        assert result["high"] == 195.0
        assert result["low"] == 189.0
        assert result["open"] == 190.0
        assert result["close"] == 194.0
        assert result["bars"] == 3
        assert result["avg_volume"] == 1500000.0

    async def test_get_ohlcv_symbol_error(self, mock_tvdata):
        """Unknown symbol raises ValueError."""
        td, ws = mock_tvdata
        ws.recv.side_effect = [
            _symbol_error("cs_test", "FAKE"),
        ]

        with pytest.raises(ValueError, match="FAKE"):
            await td.get_ohlcv("FAKE", "1D", 10)

    async def test_get_ohlcv_empty(self, mock_tvdata):
        """No bars received returns empty list."""
        td, ws = mock_tvdata
        session = _session_id()
        ws.recv.side_effect = [
            _series_loading(session),
            _series_completed(session),
        ]

        result = await td.get_ohlcv("NASDAQ:AAPL", "1D", 100)
        assert result == []

    async def test_get_ohlcv_multiple_du(self, mock_tvdata):
        """Multiple du messages before series_completed are accumulated."""
        td, ws = mock_tvdata
        session = _session_id()

        batch1 = [(1704067200, 190.0, 191.0, 189.5, 190.5, 1000000)]
        batch2 = [(1704153600, 190.5, 192.0, 190.0, 191.5, 1200000)]
        ws.recv.side_effect = [
            _series_loading(session),
            _du_frame(session, batch1),
            _du_frame(session, batch2),
            _series_completed(session),
        ]

        result = await td.get_ohlcv("NASDAQ:AAPL", "1D", 2)
        assert len(result) == 2

    async def test_heartbeat_echoed(self, mock_tvdata):
        """Heartbeat frames are echoed back and not parsed."""
        td, ws = mock_tvdata
        session = _session_id()

        bars = [(1704067200, 190.0, 191.0, 189.5, 190.5, 1000000)]
        ws.recv.side_effect = [
            _heartbeat_frame(42),
            _heartbeat_frame(99),
            _series_loading(session),
            _du_frame(session, bars),
            _series_completed(session),
        ]

        result = await td.get_ohlcv("NASDAQ:AAPL", "1D", 1)
        assert len(result) == 1
        # Both heartbeats should have been echoed back
        assert ws.send.call_count >= 2  # at least 2 heartbeats echoed

    async def test_concatenated_frames(self, mock_tvdata):
        """Multiple frames in a single WebSocket message."""
        td, ws = mock_tvdata
        session = _session_id()

        bars = [(1704067200, 190.0, 191.0, 189.5, 190.5, 1000000)]
        du = _du_frame(session, bars)
        completed = _series_completed(session)
        # Concatenate them
        ws.recv.side_effect = [du + completed]

        result = await td.get_ohlcv("NASDAQ:AAPL", "1D", 1)
        assert len(result) == 1

    async def test_not_connected_error(self):
        """Calling get_ohlcv outside context manager raises RuntimeError."""
        td = TVData()
        with pytest.raises(RuntimeError, match="Not connected"):
            await td.get_ohlcv("NASDAQ:AAPL", "1D", 1)

    async def test_context_manager(self):
        """TVData works as an async context manager."""
        ws = AsyncMock()
        ws.close = AsyncMock()
        with patch("pytvtools_core.tvdata._ws_connect", AsyncMock(return_value=ws)):
            async with TVData() as td:
                assert td._ws is not None
            ws.close.assert_awaited_once()

    async def test_timescale_update(self, mock_tvdata):
        """timescale_update messages are parsed like du."""
        td, ws = mock_tvdata
        session = _session_id()

        bars = [(1704067200, 190.0, 191.0, 189.5, 190.5, 1000000)]
        entries = [{"i": 0, "v": list(bars[0])}]
        data = {"sds_1": {"s": entries, "ns": {"d": "", "indexes": "s"}, "t": "s"}}
        frame = _tv_frame("timescale_update", [session, data])

        ws.recv.side_effect = [
            _series_loading(session),
            frame,
            _series_completed(session),
        ]

        result = await td.get_ohlcv("NASDAQ:AAPL", "1D", 1)
        assert len(result) == 1

    async def test_malformed_frame_skipped(self, mock_tvdata):
        """Malformed JSON frames are silently skipped."""
        td, ws = mock_tvdata
        session = _session_id()

        bars = [(1704067200, 190.0, 191.0, 189.5, 190.5, 1000000)]
        bad_frame = "~m~10~m~not-json"
        ws.recv.side_effect = [
            bad_frame,
            _series_loading(session),
            _du_frame(session, bars),
            _series_completed(session),
        ]

        result = await td.get_ohlcv("NASDAQ:AAPL", "1D", 1)
        assert len(result) == 1


class TestTVDataMulti:
    """get_ohlcv_multi parallel fetch tests."""

    async def test_get_ohlcv_multi_basic(self):
        """Multiple symbols fetched in parallel."""
        with patch("pytvtools_core.tvdata._ws_connect", AsyncMock()):
            with patch.object(TVData, "get_ohlcv") as mock_get:
                async def side_effect(sym, *args, **kwargs):
                    return {"symbol": sym, "bars": 100}
                mock_get.side_effect = side_effect

                td = TVData()
                result = await td.get_ohlcv_multi(["A", "B", "C"], "1D", 100)

        assert result == {
            "A": {"symbol": "A", "bars": 100},
            "B": {"symbol": "B", "bars": 100},
            "C": {"symbol": "C", "bars": 100},
        }
        assert mock_get.call_count == 3

    async def test_get_ohlcv_multi_error_isolation(self):
        """An error for one symbol doesn't affect others."""
        with patch("pytvtools_core.tvdata._ws_connect", AsyncMock()):
            with patch.object(TVData, "get_ohlcv") as mock_get:
                async def side_effect(sym, *args, **kwargs):
                    if sym == "B":
                        raise ValueError("bad symbol")
                    return {"symbol": sym, "bars": 100}
                mock_get.side_effect = side_effect

                td = TVData()
                result = await td.get_ohlcv_multi(["A", "B", "C"], "1D", 100)

        assert result["A"] == {"symbol": "A", "bars": 100}
        assert "error" in result["B"]
        assert result["C"] == {"symbol": "C", "bars": 100}

    async def test_get_ohlcv_multi_empty(self):
        """Empty symbol list returns empty dict."""
        td = TVData()
        result = await td.get_ohlcv_multi([], "1D", 100)
        assert result == {}
