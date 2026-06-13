"""
Direct WebSocket fetcher for TradingView OHLCV data.

Connects to TradingView's WebSocket protocol directly (no CDP, no browser)
to fetch OHLCV bar data. Useful for fast multi-symbol scanning where
custom/private indicator values are not needed.

Usage:
    async with TVData() as d:
        bars = await d.get_ohlcv("NASDAQ:AAPL", "1D", 100)
        summary = await d.get_ohlcv("BINANCE:BTCUSDT", "1D", 500, summary=True)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import string
from typing import Any

import websockets

logger = logging.getLogger(__name__)


async def _ws_connect(url: str, **kwargs: Any) -> Any:
    """websockets >= 16: connect() returns an async context manager, not awaitable."""
    return await websockets.connect(url, **kwargs).__aenter__()


_WS_URL = "wss://data.tradingview.com/socket.io/websocket?from=chart%2F"
_AUTH_TOKEN = "unauthorized_user_token"
_TIMEOUT = 30

_HEARTBEAT_RE = re.compile(r"~m~\d+~m~~h~\d+$")
_FRAME_RE = re.compile(r"~m~\d+~m~")


def _frame(msg: dict) -> str:
    payload = json.dumps(msg, separators=(",", ":"))
    return f"~m~{len(payload)}~m~{payload}"


def _session_id(prefix: str = "cs_") -> str:
    return prefix + "".join(secrets.choice(string.ascii_lowercase) for _ in range(12))


class TVData:
    """Direct WebSocket OHLCV fetcher for TradingView.

    Uses TradingView's undocumented WebSocket protocol directly.
    No browser or CDP needed. Each connection creates its own chart
    session with independent rate limits.

    Usage:
        async with TVData() as d:
            bars = await d.get_ohlcv("NASDAQ:AAPL", "1D", 100)
    """

    def __init__(self) -> None:
        self._ws: websockets.WebSocketClientProtocol | None = None

    async def __aenter__(self) -> TVData:
        self._ws = await _ws_connect(
            _WS_URL,
            additional_headers={
                "Origin": "https://www.tradingview.com",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            },
            open_timeout=10,
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def get_ohlcv(
        self,
        symbol: str,
        interval: str = "1D",
        bars_count: int = 100,
        *,
        summary: bool = False,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """Fetch OHLCV bars for a symbol.

        Args:
            symbol: TradingView symbol (e.g. "NASDAQ:AAPL", "BINANCE:BTCUSDT").
            interval: Timeframe ("1", "5", "15", "60", "D", "W", etc.).
            bars_count: Number of bars to fetch.  Limits vary by
                timeframe:
                - Intraday (1/5/15/60): ~5000-6000 (chart inception)
                - Daily: 5000 safe (WS frame hits 1MB at ~8000)
                - Weekly: ~5600, Monthly: ~1670 (chart inception)
            summary: If True, return summary stats instead of all bars.

        Returns:
            List of bar dicts {timestamp, open, high, low, close, volume}
            or a summary dict when summary=True.
        """
        if self._ws is None:
            raise RuntimeError("Not connected. Use 'async with TVData()'")

        chart_session = _session_id("cs_")
        bars: list[dict[str, Any]] = []

        await self._ws.send(_frame({"m": "set_auth_token", "p": [_AUTH_TOKEN]}))
        await self._ws.send(_frame({"m": "chart_create_session", "p": [chart_session, ""]}))

        symbol_desc = json.dumps({
            "symbol": symbol,
            "adjustment": "splits",
            "backadjustment": "default",
        })
        await self._ws.send(_frame({
            "m": "resolve_symbol",
            "p": [chart_session, "sds_sym_1", f"={symbol_desc}"],
        }))
        await self._ws.send(_frame({
            "m": "create_series",
            "p": [chart_session, "sds_1", "s1", "sds_sym_1", interval, bars_count, ""],
        }))

        loop = asyncio.get_running_loop()
        deadline = loop.time() + _TIMEOUT

        while loop.time() < deadline:
            raw = await self._ws.recv()

            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")

            if _HEARTBEAT_RE.match(raw):
                await self._ws.send(raw)
                continue

            for item in _FRAME_RE.split(raw):
                if not item:
                    continue
                # Echo heartbeat fragments that may be concatenated
                # with data frames in a single recv().
                if item.startswith("~h~"):
                    await self._ws.send(item)
                    continue
                try:
                    msg = json.loads(item)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("m")
                params = msg.get("p", [])

                if msg_type in ("du", "timescale_update"):
                    bars.extend(self._parse_bars(params))
                elif msg_type == "series_completed":
                    return self._result(bars, symbol, interval, summary)
                elif msg_type == "symbol_error":
                    msg_text = str(params)
                    raise ValueError(f"Symbol error for {symbol}: {msg_text}")

        return self._result(bars, symbol, interval, summary)

    def _parse_bars(self, params: list[Any]) -> list[dict[str, Any]]:
        """Extract OHLCV bars from du/timescale_update message params.

        Format: p = [session_id, { series_id: { s: [{i, v: [ts,o,h,l,c,v]}] } }]
        """
        if not isinstance(params, list) or len(params) < 2:
            return []
        payload = params[1]
        if not isinstance(payload, dict):
            return []

        bars: list[dict[str, Any]] = []
        for _name, series_data in payload.items():
            if not isinstance(series_data, dict):
                continue
            entries = series_data.get("s", [])
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                vals = entry.get("v")
                if not isinstance(vals, list) or len(vals) < 5:
                    continue
                bars.append({
                    "timestamp": vals[0],
                    "open": vals[1],
                    "high": vals[2],
                    "low": vals[3],
                    "close": vals[4],
                    "volume": vals[5] if len(vals) > 5 else 0,
                })
        return bars

    async def get_ohlcv_multi(
        self,
        symbols: list[str],
        interval: str = "1D",
        bars_count: int = 100,
        *,
        summary: bool = False,
        max_concurrent: int = 5,
    ) -> dict[str, Any]:
        """Fetch OHLCV for multiple symbols in parallel.

        Opens one WebSocket connection per symbol, up to ``max_concurrent``
        at a time.  Each connection is independent — errors for one symbol
        don't affect others.

        Args:
            symbols: List of TradingView symbols (e.g. ``"NASDAQ:AAPL"``).
            interval: Timeframe (``"1"``, ``"5"``, ``"15"``, ``"60"``,
                ``"D"``, ``"W"``, etc.).
            bars_count: Number of bars per symbol.  See :meth:`get_ohlcv`
                for per-symbol/per-TF limits.
            summary: If True, return summary stats instead of all bars.
            max_concurrent: Max parallel connections (default 5).

        Returns
        -------
        dict[str, Any]
            ``{symbol: result}`` — each result is the same format as
            :meth:`get_ohlcv`.  On error, ``{symbol: {"error": str}}``.
        """
        sem = asyncio.Semaphore(max_concurrent)

        async def _fetch(sym: str) -> Any:
            async with sem:
                async with TVData() as d:
                    return await d.get_ohlcv(sym, interval, bars_count, summary=summary)

        tasks = [_fetch(s) for s in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        out: dict[str, Any] = {}
        for sym, result in zip(symbols, results):
            if isinstance(result, Exception):
                out[sym] = {"error": str(result)}
            else:
                out[sym] = result
        return out

    def _result(
        self,
        bars: list[dict[str, Any]],
        symbol: str,
        interval: str,
        summary: bool,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        bars.sort(key=lambda b: b["timestamp"])
        if summary and bars:
            closes = [b["close"] for b in bars]
            return {
                "symbol": symbol,
                "interval": interval,
                "high": max(b["high"] for b in bars),
                "low": min(b["low"] for b in bars),
                "open": bars[0]["open"],
                "close": bars[-1]["close"],
                "avg_volume": sum(b["volume"] for b in bars) / len(bars),
                "range": f"{closes[-1] - closes[0]:.2f}",
                "bars": len(bars),
            }
        return bars
