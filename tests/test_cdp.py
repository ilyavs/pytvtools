"""Tests for cdp.py — CdpConnection WebSocket transport."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import websockets

from pytvtools.cdp import (
    CdpConnection,
    CdpError,
    _ws_connect,
    find_tv_target,
    get_targets,
    make_ws_url,
    wait_for_cdp,
)


class TestCdpConnection:
    """CdpConnection wraps a CDP WebSocket and sends Runtime.evaluate."""

    async def test_connect_enables_runtime(self, mock_ws):
        mock_ws.recv.side_effect = [
            json.dumps({"id": 1, "result": {}}),
        ]
        with patch("pytvtools.cdp._ws_connect", AsyncMock(return_value=mock_ws)):
            cdp = CdpConnection("ws://localhost:9222/devtools/page/abc")
            await cdp.connect()
        assert mock_ws.send.call_count == 1
        sent = json.loads(mock_ws.send.call_args[0][0])
        assert sent == {"id": 1, "method": "Runtime.enable", "params": {}}

    async def test_evaluate_returns_value(self, mock_ws):
        mock_ws.recv.side_effect = [
            json.dumps({"id": 1, "result": {}}),                              # Runtime.enable
            json.dumps({"id": 2, "result": {"result": {"value": 42}}}),       # evaluate
        ]
        with patch("pytvtools.cdp._ws_connect", AsyncMock(return_value=mock_ws)):
            cdp = CdpConnection("ws://localhost:9222/devtools/page/abc")
            await cdp.connect()
            val = await cdp.evaluate("1 + 1")
        assert val == 42

        sent = json.loads(mock_ws.send.call_args[0][0])
        assert sent["method"] == "Runtime.evaluate"
        assert sent["params"]["expression"] == "1 + 1"
        assert sent["params"]["returnByValue"] is True
        assert sent["params"]["awaitPromise"] is False

    async def test_evaluate_with_await_promise(self, mock_ws):
        mock_ws.recv.side_effect = [
            json.dumps({"id": 1, "result": {}}),  # Runtime.enable
            json.dumps({"id": 2, "result": {"result": {"value": "done"}}}),
        ]
        with patch("pytvtools.cdp._ws_connect", AsyncMock(return_value=mock_ws)):
            cdp = CdpConnection("ws://localhost:9222/devtools/page/abc")
            await cdp.connect()
            val = await cdp.evaluate("Promise.resolve('done')", await_promise=True)
        assert val == "done"

        sent = json.loads(mock_ws.send.call_args[0][0])
        assert sent["params"]["awaitPromise"] is True

    async def test_evaluate_raises_on_js_exception(self, mock_ws):
        mock_ws.recv.side_effect = [
            json.dumps({"id": 1, "result": {}}),
            json.dumps({
                "id": 2,
                "result": {
                    "exceptionDetails": {
                        "text": "Uncaught",
                        "exception": {"description": "ReferenceError: foo is not defined"},
                    },
                },
            }),
        ]
        with patch("pytvtools.cdp._ws_connect", AsyncMock(return_value=mock_ws)):
            cdp = CdpConnection("ws://localhost:9222/devtools/page/abc")
            await cdp.connect()
            with pytest.raises(CdpError, match="ReferenceError"):
                await cdp.evaluate("foo.bar()")

    async def test_evaluate_skips_notifications(self, mock_ws):
        """Messages without an 'id' field are CDP notifications and must be skipped."""
        mock_ws.recv.side_effect = [
            json.dumps({"id": 1, "result": {}}),
            json.dumps({"method": "Runtime.consoleAPICalled", "params": {}}),
            json.dumps({"id": 2, "result": {"result": {"value": "ok"}}}),
        ]
        with patch("pytvtools.cdp._ws_connect", AsyncMock(return_value=mock_ws)):
            cdp = CdpConnection("ws://localhost:9222/devtools/page/abc")
            await cdp.connect()
            val = await cdp.evaluate("'ok'")
        assert val == "ok"

    async def test_send_raises_on_cdp_error(self, mock_ws):
        mock_ws.recv.side_effect = [
            json.dumps({"id": 1, "result": {}}),
            json.dumps({"id": 2, "error": {"code": -32000, "message": "Cannot find target"}}),
        ]
        with patch("pytvtools.cdp._ws_connect", AsyncMock(return_value=mock_ws)):
            cdp = CdpConnection("ws://localhost:9222/devtools/page/abc")
            await cdp.connect()
            with pytest.raises(CdpError, match="Cannot find target"):
                await cdp.evaluate("1")

    async def test_close(self, mock_ws):
        mock_ws.recv.side_effect = [json.dumps({"id": 1, "result": {}})]
        with patch("pytvtools.cdp._ws_connect", AsyncMock(return_value=mock_ws)):
            cdp = CdpConnection("ws://localhost:9222/devtools/page/abc")
            await cdp.connect()
            await cdp.close()
        mock_ws.close.assert_awaited_once()

    async def test_evaluate_return_by_value_false(self, mock_ws):
        mock_ws.recv.side_effect = [
            json.dumps({"id": 1, "result": {}}),
            json.dumps({"id": 2, "result": {"result": {"objectId": "abc123"}}}),
        ]
        with patch("pytvtools.cdp._ws_connect", AsyncMock(return_value=mock_ws)):
            cdp = CdpConnection("ws://localhost:9222/devtools/page/abc")
            await cdp.connect()
            obj = await cdp.evaluate("document", return_by_value=False)
        assert obj == "abc123"

    async def test_send_increments_message_id(self, mock_ws):
        mock_ws.recv.side_effect = [
            json.dumps({"id": 1, "result": {}}),
            json.dumps({"id": 2, "result": {}}),
            json.dumps({"id": 3, "result": {}}),
        ]
        with patch("pytvtools.cdp._ws_connect", AsyncMock(return_value=mock_ws)):
            cdp = CdpConnection("ws://localhost:9222/devtools/page/abc")
            await cdp.connect()
            await cdp.send_command("Runtime.evaluate", {"expression": "1"})
            await cdp.send_command("Runtime.evaluate", {"expression": "2"})
        assert mock_ws.send.call_count == 3
        ids = [json.loads(c[0][0])["id"] for c in mock_ws.send.call_args_list]
        assert ids == [1, 2, 3]


class TestHttpHelpers:
    """HTTP helper functions for CDP target discovery."""

    async def test_get_targets(self, mock_http_client):
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"id": "page1", "url": "https://www.tradingview.com/chart/", "type": "page"},
        ]
        mock_http_client.get.return_value = mock_response
        mock_http_client.__aenter__.return_value = mock_http_client

        with patch("httpx.AsyncClient", return_value=mock_http_client):
            targets = await get_targets("localhost", 9222)

        assert len(targets) == 1
        assert targets[0]["id"] == "page1"
        mock_http_client.get.assert_awaited_once_with(
            "http://localhost:9222/json/list", timeout=10
        )

    async def test_find_tv_target_finds_chart_tab(self, mock_http_client):
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"id": "1", "url": "https://www.tradingview.com/chart/AAPL/", "type": "page"},
            {"id": "2", "url": "https://www.tradingview.com/", "type": "page"},
        ]
        mock_http_client.get.return_value = mock_response
        mock_http_client.__aenter__.return_value = mock_http_client

        with patch("httpx.AsyncClient", return_value=mock_http_client):
            target = await find_tv_target("localhost", 9222)

        assert target is not None
        assert target["id"] == "1"

    async def test_find_tv_target_falls_back_to_any_tv(self, mock_http_client):
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"id": "3", "url": "https://www.tradingview.com/screener/", "type": "page"},
        ]
        mock_http_client.get.return_value = mock_response
        mock_http_client.__aenter__.return_value = mock_http_client

        with patch("httpx.AsyncClient", return_value=mock_http_client):
            target = await find_tv_target("localhost", 9222)

        assert target is not None
        assert target["id"] == "3"

    async def test_find_tv_target_returns_none(self, mock_http_client):
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"id": "4", "url": "https://google.com", "type": "page"},
        ]
        mock_http_client.get.return_value = mock_response
        mock_http_client.__aenter__.return_value = mock_http_client

        with patch("httpx.AsyncClient", return_value=mock_http_client):
            target = await find_tv_target("localhost", 9222)

        assert target is None

    async def test_wait_for_cdp_succeeds(self, mock_http_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_http_client.get.return_value = mock_response
        mock_http_client.__aenter__.return_value = mock_http_client

        with patch("httpx.AsyncClient", return_value=mock_http_client):
            ok = await wait_for_cdp("localhost", 9222, timeout=1)

        assert ok is True

    async def test_wait_for_cdp_timeout(self, mock_http_client):
        mock_http_client.get.side_effect = httpx.ConnectError("refused")
        mock_http_client.__aenter__.return_value = mock_http_client

        with patch("httpx.AsyncClient", return_value=mock_http_client):
            ok = await wait_for_cdp("localhost", 9222, timeout=0.5)

        assert ok is False

    def test_make_ws_url_uses_webSocketDebuggerUrl(self):
        target = {"webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/abc"}
        assert make_ws_url(target) == "ws://localhost:9222/devtools/page/abc"

    def test_make_ws_url_constructs_from_url(self):
        target = {
            "id": "abc",
            "devtoolsFrontendUrl": "/devtools/inspector.html?ws=localhost:9222/devtools/page/abc",
        }
        url = make_ws_url(target)
        assert "abc" in url
