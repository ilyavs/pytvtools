"""Tests for tv.py — high-level TradingView client.

All tests mock CdpConnection so no real Chrome/TradingView is needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pytvtools.tv import TV


@pytest.fixture
def mock_cdp():
    """Create a TV instance with a mocked CdpConnection, already connected."""
    cdp = AsyncMock()
    cdp.evaluate = AsyncMock()
    cdp.connect = AsyncMock()
    cdp.close = AsyncMock()
    with patch("pytvtools.tv.find_tv_target", AsyncMock(return_value={"id": "x", "webSocketDebuggerUrl": "ws://localhost:9222/x"})):
        with patch("pytvtools.tv.CdpConnection", return_value=cdp):
            tv = TV()
            tv._cdp = cdp  # already connected
            yield tv, cdp


class TestConnection:
    """TV.connect / disconnect lifecycle."""

    async def test_connect(self, mock_cdp):
        tv, cdp = mock_cdp
        await tv.connect()
        cdp.connect.assert_awaited_once()

    async def test_connect_no_target(self):
        with patch("pytvtools.tv.find_tv_target", AsyncMock(return_value=None)):
            tv = TV()
            with pytest.raises(RuntimeError, match="No TradingView chart tab found"):
                await tv.connect()

    async def test_disconnect(self, mock_cdp):
        tv, cdp = mock_cdp
        await tv.connect()
        await tv.disconnect()
        cdp.close.assert_awaited_once()

    async def test_disconnect_when_not_connected(self):
        tv = TV()
        await tv.disconnect()  # should not raise

    async def test_context_manager(self, mock_cdp):
        tv, cdp = mock_cdp
        async with tv:
            pass
        cdp.connect.assert_awaited_once()
        cdp.close.assert_awaited_once()

    async def test_context_manager_no_target(self):
        with patch("pytvtools.tv.find_tv_target", AsyncMock(return_value=None)):
            with pytest.raises(RuntimeError):
                async with TV():
                    pass


class TestChartControl:
    """Chart control methods: get_state, set_symbol, etc."""

    async def test_get_state(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.return_value = {"symbol": "NASDAQ:AAPL", "timeframe": "1D", "chartType": 1}
        result = await tv.get_state()
        assert result == {"symbol": "NASDAQ:AAPL", "timeframe": "1D", "chartType": 1}
        expr = cdp.evaluate.call_args[0][0]
        assert "TradingViewApi.chart()" in expr
        assert "symbol()" in expr
        assert "resolution()" in expr
        assert "chartType()" in expr

    async def test_set_symbol(self, mock_cdp):
        tv, cdp = mock_cdp
        await tv.set_symbol("BTCUSD")
        expr = cdp.evaluate.call_args[0][0]
        assert "setSymbol" in expr
        assert "BTCUSD" in expr

    async def test_set_timeframe(self, mock_cdp):
        tv, cdp = mock_cdp
        await tv.set_timeframe("60")
        expr = cdp.evaluate.call_args[0][0]
        assert "setResolution" in expr
        assert "60" in expr

    async def test_set_chart_type(self, mock_cdp):
        tv, cdp = mock_cdp
        await tv.set_chart_type(1)
        expr = cdp.evaluate.call_args[0][0]
        assert "setChartType" in expr
        assert "1" in expr

    async def test_scroll_to_date(self, mock_cdp):
        tv, cdp = mock_cdp
        await tv.scroll_to_date("2025-01-15")
        expr = cdp.evaluate.call_args[0][0]
        assert "scrollToDate" in expr
        assert "2025-01-15" in expr

    async def test_get_visible_range(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.return_value = {"from": 1700000000, "to": 1705000000}
        result = await tv.get_visible_range()
        assert result == {"from": 1700000000, "to": 1705000000}
        expr = cdp.evaluate.call_args[0][0]
        assert "timeRange" in expr


class TestData:
    """Data methods: get_ohlcv, get_quote, get_study_values."""

    async def test_get_ohlcv_summary(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.return_value = {"count": 3, "high": 150, "low": 100, "open": 120, "close": 140, "avg_volume": 1000000, "range": "50.00"}
        result = await tv.get_ohlcv(count=500, summary=True)
        assert result["count"] == 3
        assert result["high"] == 150

    async def test_get_ohlcv_full(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.return_value = [
            {"timestamp": 1700000000, "open": 100, "high": 110, "low": 99, "close": 108, "volume": 500000},
        ]
        result = await tv.get_ohlcv(count=1, summary=False)
        assert len(result) == 1
        assert result[0]["close"] == 108
        expr = cdp.evaluate.call_args[0][0]
        assert "bars()" in expr

    async def test_get_quote(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.return_value = {"symbol": "AAPL"}
        result = await tv.get_quote()
        assert result["symbol"] == "AAPL"

    async def test_get_study_values_no_studies(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.return_value = {}
        result = await tv.get_study_values()
        assert result == {}

    async def test_get_study_values_with_data(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.return_value = {
            "RSI": {
                "title": "RSI (14, close)",
                "values": [
                    {"timestamp": 1700000000, "value": 45.2},
                    {"timestamp": 1700086400, "value": 52.1},
                ],
            },
        }
        result = await tv.get_study_values()
        assert "RSI" in result
        assert len(result["RSI"]["values"]) == 2

    async def test_get_study_values_error(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.return_value = {"RSI": {"error": "no data source"}}
        result = await tv.get_study_values()
        assert "error" in result["RSI"]


class TestIndicators:
    """Indicator management: add, remove."""

    async def test_add_indicator(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.return_value = "abc123"
        eid = await tv.add_indicator("RSI@tv-basicstudies")
        assert eid == "abc123"
        expr = cdp.evaluate.call_args[0][0]
        assert "_createStudy" in expr
        assert "RSI@tv-basicstudies" in expr
        assert "java" in expr

    async def test_add_indicator_custom_id(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.return_value = "custom123"
        eid = await tv.add_indicator("SFFMev")
        assert eid == "custom123"
        expr = cdp.evaluate.call_args[0][0]
        assert "SFFMev" in expr

    async def test_remove_indicator(self, mock_cdp):
        tv, cdp = mock_cdp
        await tv.remove_indicator("abc123")
        expr = cdp.evaluate.call_args[0][0]
        assert "removeEntity" in expr
        assert "abc123" in expr

    async def test_add_indicator_uses_await_promise(self, mock_cdp):
        tv, cdp = mock_cdp
        await tv.add_indicator("RSI@tv-basicstudies")
        assert cdp.evaluate.call_args[1].get("await_promise") is True


class TestPineDrawings:
    """Pine Script drawing methods: lines, labels."""

    async def test_get_pine_lines(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.return_value = [
            {"id": "l1", "price": 150.5, "text": "support"},
            {"id": "l2", "price": 155.0, "text": "resistance"},
        ]
        lines = await tv.get_pine_lines()
        assert len(lines) == 2
        assert lines[0]["price"] == 150.5

    async def test_get_pine_lines_with_filter(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.return_value = [
            {"id": "l1", "price": 150.5, "text": "support"},
            {"id": "l2", "price": 155.0, "text": "resistance"},
        ]
        lines = await tv.get_pine_lines(study_filter="support")
        assert len(lines) == 1
        assert lines[0]["id"] == "l1"

    async def test_get_pine_lines_empty(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.return_value = None
        lines = await tv.get_pine_lines()
        assert lines == []

    async def test_get_pine_labels(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.return_value = [
            {"text": "entry", "price": 100, "time": 1700000000},
        ]
        labels = await tv.get_pine_labels(max_labels=10)
        assert len(labels) == 1
        assert labels[0]["text"] == "entry"

    async def test_get_pine_labels_with_filter(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.return_value = [
            {"text": "entry long", "price": 100, "time": 1700000000},
            {"text": "exit", "price": 105, "time": 1700086400},
        ]
        labels = await tv.get_pine_labels(study_filter="long")
        assert len(labels) == 1

    async def test_get_pine_labels_empty(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.return_value = None
        labels = await tv.get_pine_labels()
        assert labels == []


class TestCapture:
    """Screenshot capture."""

    async def test_capture_screenshot(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp._send = AsyncMock(return_value={"data": "base64data"})
        result = await tv.capture_screenshot()
        assert result == "base64data"
        cdp._send.assert_awaited_once_with(
            "Page.captureScreenshot",
            {"format": "png", "fromSurface": True},
        )

    async def test_capture_screenshot_not_connected(self):
        tv = TV()
        with pytest.raises(RuntimeError, match="Not connected"):
            await tv.capture_screenshot()


class TestBatch:
    """Batch operations across symbols/timeframes."""

    async def test_batch_ohlcv(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.return_value = None
        result = await tv.batch(["AAPL"], ["D"], action="ohlcv")
        assert "AAPL" in result
        assert "D" in result["AAPL"]

    async def test_batch_studies(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.return_value = {}
        result = await tv.batch(["AAPL"], ["D"], action="studies")
        assert "AAPL" in result


class TestPineEditor:
    """Pine Script editor methods."""

    async def test_pine_set_source(self, mock_cdp):
        tv, cdp = mock_cdp
        await tv.pine_set_source("//@version=6\nindicator('test')")
        expr = cdp.evaluate.call_args[0][0]
        assert "monaco-editor" in expr
        assert "insertText" in expr

    async def test_pine_compile(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.return_value = None
        result = await tv.pine_compile()
        assert "errors" in result


class TestUI:
    """Internal UI helper methods."""

    async def test_ui_click(self, mock_cdp):
        tv, cdp = mock_cdp
        await tv._ui_click("Indicators")
        expr = cdp.evaluate.call_args[0][0]
        assert "querySelectorAll" in expr
        assert "Indicators" in expr

    async def test_ui_click_not_found(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.side_effect = Exception("Button not found")
        with pytest.raises(Exception):
            await tv._ui_click("non-existent")


class TestErrorHandling:
    """Error states."""

    async def test_eval_raises_if_not_connected(self):
        tv = TV()
        with pytest.raises(RuntimeError, match="Not connected"):
            await tv._eval("1 + 1")

    async def test_eval_uses_cdp_evaluate(self, mock_cdp):
        tv, cdp = mock_cdp
        await tv.connect()
        await tv._eval("1 + 1")
        cdp.evaluate.assert_awaited_once_with("1 + 1")

    async def test_eval_passes_kwargs(self, mock_cdp):
        tv, cdp = mock_cdp
        await tv.connect()
        await tv._eval("Promise.resolve(42)", await_promise=True)
        cdp.evaluate.assert_awaited_once_with("Promise.resolve(42)", await_promise=True)


class TestScriptGeneration:
    """Verify the JS expressions generated by TV methods are well-formed."""

    async def test_ohlcv_js_has_bars(self, mock_cdp):
        tv, cdp = mock_cdp
        await tv.get_ohlcv(count=100, summary=True)
        expr = cdp.evaluate.call_args[0][0]
        assert "bars()._items" in expr
        assert "-100" in expr  # slice with count

    async def test_capture_uses_page_domain(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp._send = AsyncMock(return_value={"data": ""})
        await tv.capture_screenshot()
        cdp._send.assert_awaited_once()
        assert cdp._send.call_args[0][0] == "Page.captureScreenshot"

    async def test_study_values_js_uses_chart_api(self, mock_cdp):
        tv, cdp = mock_cdp
        await tv.get_study_values()
        expr = cdp.evaluate.call_args[0][0]
        assert "TradingViewApi.chart()" in expr
        assert "dataSourceForId" in expr
        assert "_data._items" in expr
