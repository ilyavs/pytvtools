"""Tests for tv.py — high-level TradingView client.

All tests mock CdpConnection so no real Chrome/TradingView is needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pytvtools.tv import TV, TooManyIndicatorsError, SymbolNotFoundError


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
        ready = {"isLoading": False, "domBarCount": 100, "modelBars": 500, "validBars": 500, "currentSymbol": "BTCUSD"}
        cdp.evaluate.side_effect = [
            "OLD",     # prev
            None,      # setSymbol
            "BTCUSD",  # symbol poll (differs from prev → break)
            ready, ready, ready,  # wait_for_chart_ready
        ]
        await tv.set_symbol("BTCUSD")
        expr = cdp.evaluate.call_args_list[1][0][0]
        assert "setSymbol" in expr
        assert "BTCUSD" in expr

    async def test_set_symbol_not_found(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.return_value = "SAME"
        with pytest.raises(SymbolNotFoundError, match="FAKE"):
            await tv.set_symbol("FAKE")

    async def test_set_symbol_no_data_uses_wait(self, mock_cdp):
        tv, cdp = mock_cdp
        zero = {"isLoading": False, "domBarCount": 0, "modelBars": 0, "validBars": 0, "currentSymbol": "BTCUSD"}
        cdp.evaluate.side_effect = [
            "OLD",     # prev
            None,      # setSymbol
            "NODATA",  # symbol poll (differs → break)
            zero, zero, zero, zero, zero,  # wait_for_chart_ready (barCount=0 → timeout)
        ]
        with pytest.raises(SymbolNotFoundError, match="data did not arrive"):
            await tv.set_symbol("NODATA", timeout=1)

    async def test_wait_for_chart_ready_timeout(self, mock_cdp):
        tv, cdp = mock_cdp
        loading = {"isLoading": True, "domBarCount": 0, "modelBars": 0, "validBars": 0, "currentSymbol": "OLD"}
        cdp.evaluate.side_effect = [loading] * 6
        result = await tv.wait_for_chart_ready(timeout=1)
        assert result is False

    async def test_wait_for_chart_ready_stable(self, mock_cdp):
        tv, cdp = mock_cdp
        ready = {"isLoading": False, "domBarCount": 100, "modelBars": 500, "validBars": 500, "currentSymbol": "AAPL"}
        cdp.evaluate.side_effect = [ready, ready, ready]
        result = await tv.wait_for_chart_ready(expected_symbol="AAPL", timeout=5)
        assert result is True

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
        assert "visibleRange" in expr or "first()" in expr


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

    async def test_get_indicator_data_single_plot(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.return_value = {
            "id": "abc123",
            "title": "RSI (14, close)",
            "count": 2,
            "plots": [
                {
                    "name": "RSI",
                    "values": [
                        {"timestamp": 1700000000, "value": 45.2},
                        {"timestamp": 1700086400, "value": 52.1},
                    ],
                }
            ],
        }
        result = await tv.get_indicator_data("abc123")
        assert result["id"] == "abc123"
        assert result["title"] == "RSI (14, close)"
        assert result["count"] == 2
        assert len(result["plots"]) == 1
        assert result["plots"][0]["name"] == "RSI"
        assert result["plots"][0]["values"][0]["value"] == 45.2

    async def test_get_indicator_data_multi_plot(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.return_value = {
            "id": "xyz789",
            "title": "BB (20, close, 2)",
            "count": 1,
            "plots": [
                {"name": "Basis", "values": [{"timestamp": 1700000000, "value": 150.5}]},
                {"name": "Upper", "values": [{"timestamp": 1700000000, "value": 155.0}]},
                {"name": "Lower", "values": [{"timestamp": 1700000000, "value": 146.0}]},
            ],
        }
        result = await tv.get_indicator_data("xyz789")
        assert result["count"] == 1
        assert len(result["plots"]) == 3
        assert result["plots"][0]["name"] == "Basis"
        assert result["plots"][2]["values"][0]["value"] == 146.0

    async def test_get_indicator_data_not_found(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.return_value = None
        result = await tv.get_indicator_data("nonexistent")
        assert result is None


class TestIndicators:
    """Indicator management: add, remove."""

    async def test_add_indicator(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.side_effect = [[], "abc123"]
        eid = await tv.add_indicator("RSI@tv-basicstudies")
        assert eid == "abc123"
        assert "abc123" in tv._indicator_ids
        # Second call carries the _createStudy expression
        expr = cdp.evaluate.call_args_list[1][0][0]
        assert "_createStudy" in expr
        assert "RSI@tv-basicstudies" in expr
        assert "java" in expr

    async def test_add_indicator_std_id(self, mock_cdp):
        """STD; prefix uses pine-type _createStudy."""
        tv, cdp = mock_cdp
        cdp.evaluate.side_effect = [[], "sma123"]
        eid = await tv.add_indicator("STD;SMA")
        assert eid == "sma123"
        expr = cdp.evaluate.call_args_list[1][0][0]
        assert "_createStudy" in expr
        assert "STD;SMA" in expr
        assert "pine" in expr

    async def test_add_indicator_custom_id(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.side_effect = [[], "custom123"]
        eid = await tv.add_indicator("SFFMev")
        assert eid == "custom123"
        expr = cdp.evaluate.call_args_list[1][0][0]
        assert "SFFMev" in expr

    async def test_add_indicator_limit(self, mock_cdp):
        tv, cdp = mock_cdp
        tv._indicator_ids = {"eid1", "eid2"}
        cdp.evaluate.side_effect = [["eid1", "eid2"]]
        with pytest.raises(TooManyIndicatorsError):
            await tv.add_indicator("RSI@tv-basicstudies")

    async def test_remove_indicator(self, mock_cdp):
        tv, cdp = mock_cdp
        tv._indicator_ids = {"abc123"}
        await tv.remove_indicator("abc123")
        assert "abc123" not in tv._indicator_ids
        expr = cdp.evaluate.call_args[0][0]
        assert "removeEntity" in expr
        assert "abc123" in expr

    async def test_remove_all_indicators(self, mock_cdp):
        tv, cdp = mock_cdp
        tv._indicator_ids = {"eid1", "eid2"}
        await tv.remove_all_indicators()
        assert tv._indicator_ids == set()
        expr = cdp.evaluate.call_args[0][0]
        assert "removeAllStudies" in expr

    async def test_add_indicator_uses_await_promise(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.side_effect = [[], "abc123"]
        await tv.add_indicator("RSI@tv-basicstudies")
        assert cdp.evaluate.call_args_list[1][1].get("await_promise") is True

    async def test_add_indicator_display_name(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.side_effect = [[], "abc123"]
        eid = await tv.add_indicator("Relative Strength Index")
        assert eid == "abc123"
        assert "abc123" in tv._indicator_ids
        # Should use createStudy (public API), not _createStudy
        expr = cdp.evaluate.call_args_list[1][0][0]
        assert "createStudy" in expr
        assert "_createStudy" not in expr
        assert "Relative Strength Index" in expr

    async def test_add_indicator_display_name_not_found(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.side_effect = [[], None]  # createStudy returned None
        eid = await tv.add_indicator("NonExistent Indicator")
        assert eid is None
        assert len(tv._indicator_ids) == 0

    async def test_add_indicator_pub_id(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.side_effect = [[], "pub123"]
        eid = await tv.add_indicator("PUB;85")
        assert eid == "pub123"
        assert "pub123" in tv._indicator_ids
        expr = cdp.evaluate.call_args_list[1][0][0]
        assert "_createStudy" in expr
        assert "PUB;85" in expr
        assert "pine" in expr

    async def test_add_indicator_with_inputs(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.side_effect = [[], "abc123", True]
        eid = await tv.add_indicator("RSI@tv-basicstudies", inputs={"length": 14})
        assert eid == "abc123"
        # Call 1: _get_study_ids, Call 2: _createStudy, Call 3: set_indicator_inputs
        assert len(cdp.evaluate.call_args_list) == 3
        expr1 = cdp.evaluate.call_args_list[1][0][0]
        assert "_createStudy" in expr1
        assert "RSI@tv-basicstudies" in expr1
        expr2 = cdp.evaluate.call_args_list[2][0][0]
        assert "dataSourceForId" in expr2
        assert "length" in expr2

    async def test_add_indicator_with_inputs_display_name(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.side_effect = [[], "abc123", True]
        eid = await tv.add_indicator("Relative Strength Index", inputs={"length": 14})
        assert eid == "abc123"
        assert len(cdp.evaluate.call_args_list) == 3
        expr1 = cdp.evaluate.call_args_list[1][0][0]
        assert "createStudy" in expr1
        assert "_createStudy" not in expr1
        expr2 = cdp.evaluate.call_args_list[2][0][0]
        assert "dataSourceForId" in expr2
        assert "length" in expr2

    async def test_add_indicator_with_inputs_no_eid(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.side_effect = [[], None]  # creation returned None
        eid = await tv.add_indicator("RSI@tv-basicstudies", inputs={"length": 14})
        assert eid is None
        # Should NOT have called set_indicator_inputs (only 2 calls)
        assert len(cdp.evaluate.call_args_list) == 2

    async def test_set_indicator_inputs(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.return_value = True
        await tv.set_indicator_inputs("abc123", {"length": 20, "source": "close"})
        expr = cdp.evaluate.call_args[0][0]
        assert "dataSourceForId" in expr
        assert "_study" in expr

    async def test_set_indicator_inputs_empty(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.return_value = True
        await tv.set_indicator_inputs("abc123", {})
        expr = cdp.evaluate.call_args[0][0]
        assert "fullRecalc" in expr

    async def test_get_indicator_count(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.return_value = ["eid1", "eid2"]
        count = await tv.get_indicator_count()
        assert count == 2

    async def test_get_indicator_count_empty(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.return_value = []
        count = await tv.get_indicator_count()
        assert count == 0


class TestIndicatorSearch:
    """Indicator search via internal registry + _handleSearch."""

    async def test_search_indicators(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.side_effect = [
            None,            # _close_dialogs: body.click
            None,            # _close_dialogs: Escape
            None,            # dialog open
            [{"id": "STD;RSI", "name": "Relative Strength Index"}],  # built-in
            None,            # _handleSearch
            [                # community
                {"id": "PUB;131", "name": "RSI Candles"},
                {"id": "PUB;197", "name": "RSI Bands"},
            ],
            None,            # _close_dialogs: body.click
            None,            # _close_dialogs: Escape
        ]
        results = await tv.search_indicators("RSI")
        assert len(results) == 3
        # built-in first
        assert results[0]["id"] == "STD;RSI"
        assert results[0]["name"] == "Relative Strength Index"
        assert results[0]["study_id"] == "STD;RSI"
        # then community
        assert results[1]["id"] == "PUB;131"
        assert results[1]["study_id"] == "PUB;131"
        # Verify _handleSearch was called (index 4, after body.click, Escape, dialog open, built-in search)
        search_expr = cdp.evaluate.call_args_list[4][0][0]
        assert "_handleSearch" in search_expr

    async def test_search_indicators_empty(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.side_effect = [
            None,  # _close_dialogs: body.click
            None,  # _close_dialogs: Escape
            None,  # dialog open
            [],    # no built-in matches
            None,  # _handleSearch
            [],    # no community matches
            None,  # _close_dialogs: body.click
            None,  # _close_dialogs: Escape
        ]
        results = await tv.search_indicators("zzzz")
        assert results == []

    async def test_search_indicators_only_builtin(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.side_effect = [
            None,  # _close_dialogs: body.click
            None,  # _close_dialogs: Escape
            None,  # dialog open
            [{"id": "STD;RSI", "name": "Relative Strength Index"}],
            None,
            [],    # no community matches
            None,  # _close_dialogs: body.click
            None,  # _close_dialogs: Escape
        ]
        results = await tv.search_indicators("RSI")
        assert len(results) == 1
        assert results[0]["study_id"] == "STD;RSI"

    async def test_search_indicators_only_community(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.side_effect = [
            None,  # _close_dialogs: body.click
            None,  # _close_dialogs: Escape
            None,  # dialog open
            [],    # no built-in matches
            None,
            [{"id": "PUB;42", "name": "DSS Bressert"}],
            None,  # _close_dialogs: body.click
            None,  # _close_dialogs: Escape
        ]
        results = await tv.search_indicators("DSS")
        assert len(results) == 1
        assert results[0]["id"] == "PUB;42"
        assert results[0]["study_id"] == "PUB;42"

    async def test_search_indicators_none_results(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.side_effect = [
            None,  # _close_dialogs: body.click
            None,  # _close_dialogs: Escape
            None,  # dialog open
            None,  # built-in query returned None
            None,
            None,  # community query returned None
            None,  # _close_dialogs: body.click
            None,  # _close_dialogs: Escape
        ]
        results = await tv.search_indicators("RSI")
        assert results == []

    async def test_search_indicators_dedup(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.side_effect = [
            None,  # _close_dialogs: body.click
            None,  # _close_dialogs: Escape
            None,  # dialog open
            [{"id": "STD;RSI", "name": "Relative Strength Index"}],
            None,
            [{"id": "STD;RSI", "name": "Relative Strength Index"}],  # same ID from community
            None,  # _close_dialogs: body.click
            None,  # _close_dialogs: Escape
        ]
        results = await tv.search_indicators("RSI")
        assert len(results) == 1  # deduplicated


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
        cdp.send_command = AsyncMock(return_value={"data": "base64data"})
        result = await tv.capture_screenshot()
        assert result == "base64data"
        cdp.send_command.assert_awaited_once_with(
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
        ready = {"isLoading": False, "domBarCount": 100, "modelBars": 500, "validBars": 500, "currentSymbol": "AAPL"}
        restore_ready = {"isLoading": False, "domBarCount": 100, "modelBars": 500, "validBars": 500, "currentSymbol": "BTCUSD"}
        cdp.evaluate.side_effect = [
            {"symbol": "BTCUSD", "timeframe": "D", "chartType": 1},  # get_state
            "BTCUSD", None, "AAPL",  # set_symbol AAPL (wait_data=False — no ready x3)
            None,                # set_timeframe
            {"count": 3, "high": 150, "low": 100, "open": 120, "close": 140, "avg_volume": 1000000, "range": "50.00"},  # get_ohlcv
            "AAPL", None, "BTCUSD", restore_ready, restore_ready, restore_ready,  # restore set_symbol
            None,                # restore set_timeframe
        ]
        result = await tv.batch(["AAPL"], ["D"], action="ohlcv")
        assert "AAPL" in result
        assert "D" in result["AAPL"]

    async def test_batch_studies(self, mock_cdp):
        tv, cdp = mock_cdp
        ready = {"isLoading": False, "domBarCount": 100, "modelBars": 500, "validBars": 500, "currentSymbol": "AAPL"}
        restore_ready = {"isLoading": False, "domBarCount": 100, "modelBars": 500, "validBars": 500, "currentSymbol": "BTCUSD"}
        cdp.evaluate.side_effect = [
            {"symbol": "BTCUSD", "timeframe": "D", "chartType": 1},  # get_state
            "BTCUSD", None, "AAPL",  # set_symbol AAPL (wait_data=False — no ready x3)
            None,                # set_timeframe
            {"RSI": {"title": "RSI", "values": [{"timestamp": 1, "value": 50}]}},
            "AAPL", None, "BTCUSD", restore_ready, restore_ready, restore_ready,  # restore set_symbol
            None,                # restore set_timeframe
        ]
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
        cdp.evaluate.side_effect = [[], None, None, None]
        await tv.connect()
        await tv._eval("1 + 1")

    async def test_eval_passes_kwargs(self, mock_cdp):
        tv, cdp = mock_cdp
        cdp.evaluate.side_effect = [[], None, None, None]
        await tv.connect()
        await tv._eval("Promise.resolve(42)", await_promise=True)
        call = cdp.evaluate.call_args_list[-1]
        assert call[0][0] == "Promise.resolve(42)"
        assert call[1].get("await_promise") is True


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
        cdp.send_command = AsyncMock(return_value={"data": ""})
        await tv.capture_screenshot()
        cdp.send_command.assert_awaited_once()
        assert cdp.send_command.call_args[0][0] == "Page.captureScreenshot"

    async def test_study_values_js_uses_chart_api(self, mock_cdp):
        tv, cdp = mock_cdp
        await tv.get_study_values()
        expr = cdp.evaluate.call_args[0][0]
        assert "TradingViewApi.chart()" in expr
        assert "dataSourceForId" in expr
        assert "_data._items" in expr


