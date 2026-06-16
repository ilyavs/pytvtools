"""Compare TradingView indicator values against Python computations.

Usage::

    from pytvtools import TV
    from pytvtools.indicator_parity import compare_indicator, ParityReport

    async with TV() as tv:
        report = await compare_indicator(tv, "BINANCE:BTCUSDT", "1D", "STD;RSI")

    print(report.summary())
    print(report.mismatches[:5])
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pytvtools.indicators import rsi, sma, ema, mfi
from pytvtools.tv import TV

logger = logging.getLogger(__name__)

# Map study entity IDs to their Python computation function
_BUILTIN_COMPUTERS: dict[str, Any] = {
    "STD;RSI": rsi,
    "STD;SMA": sma,
    "STD;EMA": ema,
    "STD;Money_Flow": mfi,
}

# Convenience aliases → canonical TV study ID
_STUDY_ID_ALIASES: dict[str, str] = {
    "STD;MFI": "STD;Money_Flow",
    "MFI": "STD;Money_Flow",
}


def _resolve_study_id(indicator: str) -> str:
    """Resolve convenience aliases to canonical TV study IDs."""
    if indicator in _BUILTIN_COMPUTERS:
        return indicator
    return _STUDY_ID_ALIASES.get(indicator, indicator)


def _detect_computer(indicator: str) -> Any | None:
    """Find the Python function for a given indicator identifier."""
    if indicator in _BUILTIN_COMPUTERS:
        return _BUILTIN_COMPUTERS[indicator]
    aliased = _STUDY_ID_ALIASES.get(indicator)
    if aliased and aliased in _BUILTIN_COMPUTERS:
        return _BUILTIN_COMPUTERS[aliased]
    name = indicator.split(";", 1)[-1] if ";" in indicator else indicator
    return _BUILTIN_COMPUTERS.get(name)


class Mismatch:
    """One bar where Python and TradingView disagree."""

    def __init__(self, timestamp: int, py_val: float | None, tv_val: float | None, delta: float):
        self.timestamp = timestamp
        self.py_val = py_val
        self.tv_val = tv_val
        self.delta = delta

    def __repr__(self) -> str:
        return (
            f"Mismatch(ts={self.timestamp}, py={self.py_val}, "
            f"tv={self.tv_val}, delta={self.delta:.6f})"
        )


class ParityReport:
    """Result of comparing Python vs TradingView indicator values."""

    def __init__(
        self,
        symbol: str,
        timeframe: str,
        indicator: str,
        total_bars: int,
        matched: int,
        mismatches: list[Mismatch],
        tolerance: float,
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.indicator = indicator
        self.total_bars = total_bars
        self.matched = matched
        self.mismatches = mismatches
        self.tolerance = tolerance

    @property
    def match_rate(self) -> float:
        if self.total_bars == 0:
            return 0.0
        return self.matched / self.total_bars * 100

    def summary(self) -> str:
        return (
            f"Parity: {self.indicator} on {self.symbol} ({self.timeframe})\n"
            f"  Total bars:  {self.total_bars}\n"
            f"  Matched:     {self.matched} ({self.match_rate:.1f}%)\n"
            f"  Mismatches:  {len(self.mismatches)}\n"
            f"  Tolerance:   \u00b1{self.tolerance}\n"
        )


async def compare_indicator(
    tv: TV,
    symbol: str,
    timeframe: str,
    indicator: str,
    entity_id: str | None = None,
    *,
    max_bars: int | None = None,
    tolerance: float = 0.01,
    plot_index: int = 0,
) -> ParityReport:
    """Compare a TradingView indicator against its Python equivalent.

    Parameters
    ----------
    tv : TV
        Connected TV instance.
    symbol : str
        Symbol to use (e.g. ``"BINANCE:BTCUSDT"``).
    timeframe : str
        Timeframe string.
    indicator : str
        Indicator identifier for detection (e.g. ``"STD;RSI"``).
    entity_id : str | None
        If the indicator is already added, pass its entity ID.
        If ``None``, it will be added automatically.
    max_bars : int
        Number of OHLCV bars to fetch.
    tolerance : float
        Maximum allowed absolute difference between Python and TV values.
    plot_index : int
        Which plot to compare (0 = first/main plot).
    """
    await tv.set_symbol(symbol)
    await tv.set_timeframe(timeframe)
    await tv.wait_for_chart_ready(timeout=10)

    # Fetch ALL bars so timestamps align with the indicator data source
    # (both use midnight UTC when no count limit is applied).
    bars = await tv.get_ohlcv(summary=False)
    if not bars:
        raise ValueError(f"No OHLCV data returned for {symbol} {timeframe}")

    # If max_bars is set, trim to the most recent bars
    if max_bars is not None and len(bars) > max_bars:
        bars = bars[-max_bars:]

    timestamps = [b["timestamp"] for b in bars]

    computer = _detect_computer(indicator)
    if computer is None:
        available = ", ".join(_BUILTIN_COMPUTERS)
        raise ValueError(
            f"No Python implementation known for {indicator!r}. "
            f"Available: {available}"
        )

    py_values = computer(bars)  # type: ignore[operator]

    if entity_id is None:
        study_id = _resolve_study_id(indicator)
        eid = await tv.add_indicator(study_id)
        if eid is None:
            raise RuntimeError(f"Failed to add indicator {indicator}")
        entity_id = eid

    for _ in range(15):
        tv_data = await tv.get_indicator_data(entity_id)
        if tv_data and tv_data.get("plots") and tv_data["count"] > 0:
            break
        await asyncio.sleep(0.5)
    else:
        tv_data = await tv.get_indicator_data(entity_id)
    if tv_data is None:
        raise RuntimeError(f"No data returned for indicator {entity_id}")

    plots = tv_data.get("plots", [])
    if plot_index >= len(plots):
        raise ValueError(
            f"Plot index {plot_index} out of range "
            f"(only {len(plots)} plots available)"
        )

    tv_values_by_ts: dict[int, float | None] = {}
    for entry in plots[plot_index]["values"]:
        tv_values_by_ts[int(entry["timestamp"])] = entry["value"]

    mismatches: list[Mismatch] = []
    matched = 0

    min_idx = 0
    while min_idx < len(py_values) and py_values[min_idx] is None:
        min_idx += 1

    for i in range(min_idx, len(bars)):
        ts = timestamps[i]
        py_val = py_values[i]
        tv_val = tv_values_by_ts.get(ts)

        if py_val is None or tv_val is None:
            continue

        delta = abs(py_val - tv_val)
        if delta > tolerance:
            mismatches.append(Mismatch(ts, py_val, tv_val, delta))
        else:
            matched += 1

    total = len(bars) - min_idx
    return ParityReport(
        symbol=symbol,
        timeframe=timeframe,
        indicator=indicator,
        total_bars=total,
        matched=matched,
        mismatches=mismatches,
        tolerance=tolerance,
    )
