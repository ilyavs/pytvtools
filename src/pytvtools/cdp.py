"""
Low-level Chrome DevTools Protocol transport.

Connects to a CDP-enabled Chrome, discovers targets, and evaluates JS
via the Runtime.evaluate domain over a WebSocket.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx
import websockets

logger = logging.getLogger(__name__)

# socat relays from TV_CDP_PORT (externally visible) to TV_CDP_INTERNAL_PORT
# (Chrome's loopback-only port).  Python code inside the container should
# connect directly to the internal port to avoid socat's TCP buffering
# issues (which break CDP WebSocket responses).
CDP_PORT = int(os.environ.get("TV_CDP_INTERNAL_PORT") or os.environ.get("TV_CDP_PORT", "9222"))
CDP_HOST = "localhost"




class CdpError(Exception):
    def __init__(self, msg: str, details: dict | None = None):
        self.details = details or {}
        super().__init__(msg)


async def _ws_connect(url: str, **kwargs: Any) -> Any:
    """websockets >= 16: connect() returns an async context manager, not awaitable."""
    return await websockets.connect(url, **kwargs).__aenter__()


class CdpConnection:
    """One WebSocket connection to a CDP target (page)."""

    def __init__(self, ws_url: str):
        self._ws_url = ws_url
        self._ws: Any = None
        self._msg_id = 0

    async def connect(self) -> None:
        self._ws = await _ws_connect(self._ws_url)
        await self._send("Runtime.enable")

    async def evaluate(
        self,
        expression: str,
        await_promise: bool = False,
        return_by_value: bool = True,
    ) -> Any:
        result = await self._send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": return_by_value,
                "awaitPromise": await_promise,
            },
        )
        if "exceptionDetails" in result and result["exceptionDetails"]:
            exc = result["exceptionDetails"]
            msg = exc.get("exception", {}).get(
                "description", exc.get("text", "Unknown error")
            )
            raise CdpError(f"JS error: {msg}", result)
        val = result.get("result", {})
        if return_by_value:
            return val.get("value")
        return val.get("objectId")

    async def send_command(self, method: str, params: dict | None = None) -> dict:
        """Send an arbitrary CDP command and return its result."""
        return await self._send(method, params)

    async def close(self) -> None:
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def _send(self, method: str, params: dict | None = None) -> dict:
        self._msg_id += 1
        msg = {
            "id": self._msg_id,
            "method": method,
            "params": params or {},
        }
        await self._ws.send(json.dumps(msg))
        while True:
            raw = await self._ws.recv()
            resp = json.loads(raw)
            # Skip CDP notifications (no "id" field)
            if "id" not in resp:
                continue
            if "error" in resp:
                err = resp["error"]
                raise CdpError(f"CDP error ({err.get('code')}): {err.get('message')}", err)
            return resp.get("result", {})


# ---------------------------------------------------------------------------
# HTTP helpers (no persistent connection needed)
# ---------------------------------------------------------------------------


async def get_targets(
    host: str = CDP_HOST, port: int = CDP_PORT
) -> list[dict[str, Any]]:
    """List all CDP targets (tabs)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"http://{host}:{port}/json/list", timeout=10)
        resp.raise_for_status()
        return resp.json()


async def find_tv_target(
    host: str = CDP_HOST, port: int = CDP_PORT
) -> dict[str, Any] | None:
    """Find the first tab with tradingview.com/chart open."""
    targets = await get_targets(host, port)
    for t in targets:
        url = t.get("url", "")
        if t.get("type") == "page" and "tradingview.com/chart" in url:
            return t
    for t in targets:
        url = t.get("url", "")
        if t.get("type") == "page" and "tradingview" in url.lower():
            return t
    return None


async def wait_for_cdp(
    host: str = CDP_HOST,
    port: int = CDP_PORT,
    timeout: float = 30.0,
) -> bool:
    """Poll until Chrome's CDP endpoint is reachable."""
    async with httpx.AsyncClient() as client:
        for _ in range(int(timeout / 0.5)):
            try:
                resp = await client.get(
                    f"http://{host}:{port}/json/version", timeout=2
                )
                if resp.status_code == 200:
                    return True
            except (httpx.ConnectError, httpx.TimeoutException):
                pass
    return False


def make_ws_url(target: dict[str, Any]) -> str:
    """Extract the WebSocket URL from a CDP target dict."""
    ws = target.get("webSocketDebuggerUrl")
    if ws:
        return ws
    # Fallback: try to extract from devtoolsFrontendUrl ?ws= param
    frontend = target.get("devtoolsFrontendUrl") or ""
    if "?ws=" in frontend:
        ws_param = frontend.split("?ws=", 1)[1].split("&", 1)[0]
        return f"ws://{ws_param}"
    # Last resort: construct from host + page ID
    return f"ws://{CDP_HOST}:{CDP_PORT}/devtools/page/{target['id']}"


async def get_browser_ws_url(
    host: str = CDP_HOST, port: int = CDP_PORT
) -> str:
    """Get the browser-level WebSocket URL from /json/version."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"http://{host}:{port}/json/version", timeout=10)
        resp.raise_for_status()
        return resp.json()["webSocketDebuggerUrl"]


async def close_tab(
    target_id: str,
    host: str = CDP_HOST,
    port: int = CDP_PORT,
) -> None:
    """Close a Chrome tab by target ID via the browser WebSocket."""
    browser_ws_url = await get_browser_ws_url(host, port)
    ws = await _ws_connect(browser_ws_url)
    try:
        msg = json.dumps({"id": 1, "method": "Target.closeTarget", "params": {"targetId": target_id}})
        await ws.send(msg)
        while True:
            raw = await ws.recv()
            resp = json.loads(raw)
            if resp.get("id") == 1:
                break
    finally:
        await ws.close()


async def create_new_tab(
    url: str = "about:blank",
    host: str = CDP_HOST,
    port: int = CDP_PORT,
) -> dict[str, Any]:
    """Create a new tab in Chrome via the browser WebSocket and return its target info.

    New tabs are reliably responsive to CDP commands, unlike existing
    tabs which may be in a frozen/unresponsive state.
    """
    browser_ws_url = await get_browser_ws_url(host, port)
    ws = await _ws_connect(browser_ws_url)
    try:
        msg = json.dumps({"id": 1, "method": "Target.createTarget", "params": {"url": url}})
        await ws.send(msg)
        while True:
            raw = await ws.recv()
            resp = json.loads(raw)
            if resp.get("id") == 1:
                target_id = resp["result"]["targetId"]
                break
    finally:
        await ws.close()

    # Build target info from the new tab
    page_ws_url = f"ws://{host}:{port}/devtools/page/{target_id}"
    return {
        "id": target_id,
        "type": "page",
        "url": url,
        "webSocketDebuggerUrl": page_ws_url,
    }
