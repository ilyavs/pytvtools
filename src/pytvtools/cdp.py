"""
Low-level Chrome DevTools Protocol transport.

Connects to a CDP-enabled Chrome, discovers targets, and evaluates JS
via the Runtime.evaluate domain over a WebSocket.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
import websockets.client as ws_client

logger = logging.getLogger(__name__)

CDP_PORT = 9222
CDP_HOST = "localhost"


class CdpError(Exception):
    def __init__(self, msg: str, details: dict | None = None):
        self.details = details or {}
        super().__init__(msg)


class CdpConnection:
    """One WebSocket connection to a CDP target (page)."""

    def __init__(self, ws_url: str):
        self._ws_url = ws_url
        self._ws: Any = None
        self._msg_id = 0

    async def connect(self) -> None:
        self._ws = await ws_client.connect(self._ws_url)
        # Enable the Runtime domain
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

    async def evaluate_async(self, expression: str) -> Any:
        return await self.evaluate(expression, await_promise=True)

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
        resp = json.loads(await self._ws.recv())
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
    # Construct from devtoolsFrontendUrl if needed
    host = target.get("devtoolsFrontendUrl", "").split("/")[0]
    if not host:
        host = f"{CDP_HOST}:{CDP_PORT}"
    return f"ws://{host}{target.get('devtoolsFrontendUrl', '/devtools/page/' + target['id'])}"
