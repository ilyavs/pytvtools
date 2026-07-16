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
from typing import Any, TypedDict

from pytvtools_core.types import OHLCVBar

import websockets

logger = logging.getLogger(__name__)


async def _ws_connect(url: str, **kwargs: Any) -> Any:
    """websockets >= 16: connect() returns an async context manager, not awaitable."""
    return await websockets.connect(url, **kwargs).__aenter__()


_WS_URL = "wss://data.tradingview.com/socket.io/websocket?from=chart%2F"
_TIMEOUT = 30

# Resolutions that reliably work across data sources.
# "10" and other minute-based resolutions that fail as "custom_resolution"
# on some feeds (e.g. BATS) fall back to "1" for client-side aggregation.
_RESOLUTION_FALLBACKS: dict[str, list[str]] = {
    "1": ["5", "15", "30", "60", "D"],
    "5": ["15", "30", "60", "D"],
    "10": ["5", "1", "15", "30", "60", "D"],
    "20": ["5", "1", "15", "30", "60", "D"],
    "15": ["30", "60", "D"],
    "30": ["15", "5", "1", "60", "D"],
    "45": ["15", "5", "1", "30", "60", "D"],
    "60": ["D"],
}

_HEARTBEAT_RE = re.compile(r"~m~\d+~m~~h~\d+$")
_FRAME_RE = re.compile(r"~m~\d+~m~")


def _frame(msg: dict) -> str:
    payload = json.dumps(msg, separators=(",", ":"))
    return f"~m~{len(payload)}~m~{payload}"


def _session_id(prefix: str = "cs_") -> str:
    return prefix + "".join(secrets.choice(string.ascii_lowercase) for _ in range(12))


def _should_aggregate(attempt_interval: str, target_interval: str) -> bool:
    """Should bars from attempt_interval be aggregated into target_interval?"""
    if attempt_interval == target_interval or not target_interval.isdigit():
        return False
    if not attempt_interval.isdigit():
        return False
    ai, ti = int(attempt_interval), int(target_interval)
    return ai < ti and ti % ai == 0


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
            open_timeout=30,
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
        to: int | None = None,
        summary: bool = False,
    ) -> list[OHLCVBar] | dict[str, Any]:
        """Fetch OHLCV bars for a symbol.

        Args:
            symbol: TradingView symbol (e.g. "NASDAQ:AAPL", "BINANCE:BTCUSDT").
            interval: Timeframe ("1", "5", "15", "60", "D", "W", etc.).
            bars_count: Number of bars to fetch.  Limits vary by
                timeframe:
                - Intraday (1/5/15/60): ~5000-6000 (chart inception)
                - Daily: 5000 safe (WS frame hits 1MB at ~8000)
                - Weekly: ~5600, Monthly: ~1670 (chart inception)
            to: Unix timestamp in seconds. Fetch bars ending at this
                time.  ``None`` means "latest" (default).
            summary: If True, return summary stats instead of all bars.

        Returns:
            List of bar dicts {timestamp, open, high, low, close, volume}
            or a summary dict when summary=True.
        """
        if self._ws is None:
            raise RuntimeError("Not connected. Use 'async with TVData()'")

        # Try the requested interval, falling back to alternatives if the
        # server doesn't support it (e.g. "10" fails on some data sources).
        tried: set[str] = set()
        fallbacks = [interval] + _RESOLUTION_FALLBACKS.get(interval, [])

        for attempt_interval in fallbacks:
            if attempt_interval in tried:
                continue
            tried.add(attempt_interval)

            chart_session = _session_id("cs_")
            bars: list[OHLCVBar] = []

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

            await asyncio.sleep(0.3)

            to_param = str(to) if to is not None else ""
            await self._ws.send(_frame({
                "m": "create_series",
                "p": [chart_session, "sds_1", "s1", "sds_sym_1", attempt_interval, bars_count, to_param],
            }))

            loop = asyncio.get_running_loop()
            deadline = loop.time() + _TIMEOUT
            custom_resolution_error = False

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
                        if _should_aggregate(attempt_interval, interval):
                            break
                        return self._result(bars, symbol, attempt_interval, summary)
                    elif msg_type == "series_error":
                        err_str = str(params)
                        if "custom_resolution" in err_str:
                            custom_resolution_error = True
                            break
                        raise ValueError(f"Series error for {symbol} ({attempt_interval}): {err_str}")
                    elif msg_type == "symbol_error":
                        msg_text = str(params)
                        raise ValueError(f"Symbol error for {symbol}: {msg_text}")

                if custom_resolution_error:
                    break

            if bars and not custom_resolution_error:
                if _should_aggregate(attempt_interval, interval):
                    bars = self._aggregate_1m_to_n(bars, int(interval))
                    return self._result(bars, symbol, interval, summary)
                return self._result(bars, symbol, attempt_interval, summary)

        # All fallbacks exhausted
        raise ValueError(
            f"No supported resolution for {symbol}. "
            f"Tried: {', '.join(tried)}"
        )

    def _parse_bars(self, params: list[Any]) -> list[OHLCVBar]:
        """Extract OHLCV bars from du/timescale_update message params.

        Format: p = [session_id, { series_id: { s: [{i, v: [ts,o,h,l,c,v]}] } }]
        """
        if not isinstance(params, list) or len(params) < 2:
            return []
        payload = params[1]
        if not isinstance(payload, dict):
            return []

        bars: list[OHLCVBar] = []
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

    @staticmethod
    def _aggregate_1m_to_n(bars_1m: list[OHLCVBar], n_minutes: int) -> list[OHLCVBar]:
        if not bars_1m:
            return []
        bucket_s = n_minutes * 60
        result: list[OHLCVBar] = []
        for bar in bars_1m:
            ts = int(bar["timestamp"])
            bucket_ts = (ts // bucket_s) * bucket_s
            if result and result[-1]["timestamp"] == bucket_ts:
                agg = result[-1]
                agg["high"] = max(agg["high"], bar["high"])
                agg["low"] = min(agg["low"], bar["low"])
                agg["close"] = bar["close"]
                agg["volume"] += bar["volume"]
            else:
                result.append({
                    "timestamp": bucket_ts,
                    "open": bar["open"],
                    "high": bar["high"],
                    "low": bar["low"],
                    "close": bar["close"],
                    "volume": bar["volume"],
                })
        return result

    async def get_ohlcv_all(
        self,
        symbol: str,
        interval: str = "1D",
        chunk_size: int = 4000,
        *,
        summary: bool = False,
    ) -> list[OHLCVBar] | dict[str, Any]:
        """Fetch ALL available OHLCV bars for a symbol by paginating.

        Uses a single WebSocket connection and ``request_more_data``
        to paginate backward through the full symbol history.  The
        1 MB WebSocket frame limit is avoided by using small chunk
        sizes (default 4000) and requesting deficits if a chunk is
        truncated.

        Args:
            symbol: TradingView symbol (e.g. "NASDAQ:AAPL").
            interval: Timeframe ("1", "5", "15", "60", "D", "W", etc.).
            chunk_size: Bars per pagination request (default 4000).
            summary: If True, return summary stats instead of all bars.

        Returns:
            All concatenated bars, or summary dict when summary=True.

        Raises:
            ValueError: If the symbol cannot be resolved or no supported
                resolution is found.
        """
        tried: set[str] = set()
        fallbacks = [interval] + _RESOLUTION_FALLBACKS.get(interval, [])

        for attempt_interval in fallbacks:
            if attempt_interval in tried:
                continue
            tried.add(attempt_interval)

            result = await self._fetch_all_pages(
                symbol, attempt_interval, chunk_size, summary=summary,
            )
            if result:
                if _should_aggregate(attempt_interval, interval):
                    result = self._aggregate_1m_to_n(result, int(interval))
                    return self._result(result, symbol, interval, summary)
                return result
            # If result is empty and custom_resolution error was seen, try next fallback
        return []

    async def _fetch_all_pages(
        self,
        symbol: str,
        interval: str,
        chunk_size: int,
        *,
        summary: bool = False,
    ) -> list[OHLCVBar]:
        """Fetch all bars for one interval via pagination (single session)."""
        all_bars: list[OHLCVBar] = []
        bars_before = 0
        waiting = False
        pending = 0
        custom_resolution_error = False

        cs = _session_id("cs_")
        await self._ws.send(_frame({
            "m": "chart_create_session", "p": [cs, ""],
        }))
        sd = json.dumps({
            "symbol": symbol, "adjustment": "splits", "backadjustment": "default",
        })
        await self._ws.send(_frame({
            "m": "resolve_symbol", "p": [cs, "sds_sym_1", f"={sd}"],
        }))
        await asyncio.sleep(0.3)
        await self._ws.send(_frame({
            "m": "create_series",
            "p": [cs, "sds_1", "s1", "sds_sym_1", interval, chunk_size, ""],
        }))

        deadline = asyncio.get_running_loop().time() + _TIMEOUT * 3
        consecutive_timeouts = 0
        max_consecutive_timeouts = 3
        while asyncio.get_running_loop().time() < deadline:
            try:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=10)
                consecutive_timeouts = 0
            except asyncio.TimeoutError:
                consecutive_timeouts += 1
                if consecutive_timeouts >= max_consecutive_timeouts:
                    logger.warning(
                        "Connection stalled for %s (%s) after %d timeouts — returning %d bars",
                        symbol, interval, consecutive_timeouts, len(all_bars),
                    )
                    all_bars.sort(key=lambda b: b["timestamp"])
                    return all_bars
                await asyncio.sleep(2 ** consecutive_timeouts)
                continue
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            if _HEARTBEAT_RE.match(raw):
                await self._ws.send(raw)
                continue
            for item in _FRAME_RE.split(raw):
                if not item:
                    continue
                if item.startswith("~h~"):
                    await self._ws.send(item)
                    continue
                try:
                    msg = json.loads(item)
                except json.JSONDecodeError:
                    continue
                mt = msg.get("m")
                params = msg.get("p", [])

                if mt == "timescale_update":
                    all_bars.extend(self._parse_bars(params))
                elif mt == "series_completed":
                    if waiting:
                        got = len(all_bars) - bars_before
                        if got == 0:
                            all_bars.sort(key=lambda b: b["timestamp"])
                            return all_bars
                        remaining = pending - got
                        if remaining > 5:
                            need = min(remaining, chunk_size)
                            bars_before = len(all_bars)
                            pending = need
                            await self._ws.send(_frame({
                                "m": "request_more_data", "p": [cs, "sds_1", need],
                            }))
                            continue
                        waiting = False
                    bars_before = len(all_bars)
                    pending = chunk_size
                    waiting = True
                    await self._ws.send(_frame({
                        "m": "request_more_data", "p": [cs, "sds_1", chunk_size],
                    }))
                    continue
                elif mt == "series_error":
                    err_str = str(params)
                    if "custom_resolution" in err_str:
                        custom_resolution_error = True
                        continue
                    raise ValueError(
                        f"Series error for {symbol} ({interval}): {err_str}"
                    )
                elif mt == "critical_error":
                    raise ValueError(
                        f"Critical error for {symbol}: {params}"
                    )

        all_bars.sort(key=lambda b: b["timestamp"])
        if all_bars or not custom_resolution_error:
            return all_bars
        return []

    async def get_ohlcv_multi(
        self,
        symbols: list[str],
        interval: str = "1D",
        bars_count: int = 100,
        *,
        summary: bool = False,
        max_concurrent: int = 5,
    ) -> dict[str, list[OHLCVBar] | dict[str, Any]]:
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
        dict[str, list[OHLCVBar] | dict[str, Any]]
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

        out: dict[str, list[OHLCVBar] | dict[str, Any]] = {}
        for sym, result in zip(symbols, results):
            if isinstance(result, Exception):
                out[sym] = {"error": str(result)}
            else:
                out[sym] = result
        return out

    def _result(
        self,
        bars: list[OHLCVBar],
        symbol: str,
        interval: str,
        summary: bool,
    ) -> list[OHLCVBar] | dict[str, Any]:
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
