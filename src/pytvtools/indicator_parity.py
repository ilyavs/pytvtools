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
import inspect
import logging
from typing import Any

from pytvtools_core.indicators import rsi, sma, ema, macd, mfi, bbands, atr, srsi, supertrend, dss, market_cipher_b
from pytvtools.tv import TV

logger = logging.getLogger(__name__)

# Map study entity IDs to their Python computation function
_BUILTIN_COMPUTERS: dict[str, Any] = {
    "STD;RSI": rsi,
    "STD;SMA": sma,
    "STD;EMA": ema,
    "STD;MACD": macd,
    "STD;Money_Flow": mfi,
    "STD;Bollinger_Bands": bbands,
    "STD;Average_True_Range": atr,
    "STD;Stochastic_RSI": srsi,
    "STD;Supertrend": supertrend,
    "PUB;85": dss,
    "PUB;ULSuJHspklYwmfZRjRObSo0BLF6PdP2Y": market_cipher_b,
}

# Maps TV internal input IDs (in_0, in_1, …) to Python function parameter names
_TV_INPUT_MAP: dict[str, dict[str, str]] = {
    "STD;RSI": {"in_0": "period"},
    "STD;SMA": {"in_0": "period"},
    "STD;EMA": {"in_0": "period"},
    "STD;MACD": {"in_1": "fast", "in_2": "slow", "in_3": "signal"},
    "STD;Money_Flow": {"in_0": "period"},
    "STD;Bollinger_Bands": {"in_0": "period", "in_3": "stddev"},
    "STD;Average_True_Range": {"in_0": "period"},
    "STD;Stochastic_RSI": {"in_0": "smooth_k", "in_1": "smooth_d", "in_2": "period"},
    "STD;Supertrend": {"in_0": "period", "in_1": "multiplier"},
    "PUB;85": {"in_0": "pds", "in_1": "ema_len", "in_2": "trigger_len"},
    "PUB;ULSuJHspklYwmfZRjRObSo0BLF6PdP2Y": {"in_0": "channel_length", "in_1": "average_length"},
}

# Maps TV plot names to Python dict keys for multi-plot indicators
_PLOT_KEY_MAP: dict[str, dict[str, str]] = {
    "STD;MACD": {"Histogram": "histogram", "MACD": "macd", "Signal": "signal"},
    "STD;Bollinger_Bands": {"Upper": "upper", "Basis": "basis", "Lower": "lower"},
    "STD;Stochastic_RSI": {"K": "k", "D": "d"},
    "STD;Supertrend": {"Up Trend": "up_trend", "Down Trend": "down_trend"},
    "PUB;85": {"DSS": "dss", "Trigger": "trigger"},
    "PUB;ULSuJHspklYwmfZRjRObSo0BLF6PdP2Y": {"wt1": "wt1", "wt2": "wt2"},
}

_JS_GET_STUDY_INPUTS: str = """
(function() {
    var study = TradingViewApi.chart().getStudyById(__EID__);
    if (!study) return null;
    var vals = study.getInputValues ? study.getInputValues() : [];
    var r = {};
    vals.forEach(function(v) { r[v.id] = v.value; });
    return r;
})()
"""

# Convenience aliases → canonical TV study ID
_STUDY_ID_ALIASES: dict[str, str] = {
    "RSI": "STD;RSI",
    "SMA": "STD;SMA",
    "EMA": "STD;EMA",
    "MACD": "STD;MACD",
    "STD;MFI": "STD;Money_Flow",
    "MFI": "STD;Money_Flow",
    "BB": "STD;Bollinger_Bands",
    "STD;BB": "STD;Bollinger_Bands",
    "BOLLINGER": "STD;Bollinger_Bands",
    "BOLLINGER_BANDS": "STD;Bollinger_Bands",
    "ATR": "STD;Average_True_Range",
    "STD;ATR": "STD;Average_True_Range",
    "SRSI": "STD;Stochastic_RSI",
    "STD;SRSI": "STD;Stochastic_RSI",
    "STOCH_RSI": "STD;Stochastic_RSI",
    "SUPERTREND": "STD;Supertrend",
    "STD;SUPERTREND": "STD;Supertrend",
    "ST": "STD;Supertrend",
    "DSS": "PUB;85",
    "CIPHER_B": "PUB;ULSuJHspklYwmfZRjRObSo0BLF6PdP2Y",
    "MARKET_CIPHER_B": "PUB;ULSuJHspklYwmfZRjRObSo0BLF6PdP2Y",
    "MCB": "PUB;ULSuJHspklYwmfZRjRObSo0BLF6PdP2Y",
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

    computer = _detect_computer(indicator)
    if computer is None:
        available = ", ".join(_BUILTIN_COMPUTERS)
        raise ValueError(
            f"No Python implementation known for {indicator!r}. "
            f"Available: {available}"
        )

    study_id = _resolve_study_id(indicator)

    if entity_id is None:
        eid = await tv.add_indicator(study_id)
        if eid is None:
            raise RuntimeError(f"Failed to add indicator {indicator}")
        entity_id = eid

    # Read TV's actual input values so Python computation matches exactly.
    py_kwargs: dict[str, Any] = {}
    if study_id in _TV_INPUT_MAP:
        js = _JS_GET_STUDY_INPUTS.replace("__EID__", repr(entity_id))
        tv_raw_inputs = await tv._eval(js)
        if tv_raw_inputs:
            local_map = _TV_INPUT_MAP[study_id]
            sig = inspect.signature(computer)
            for tv_id, py_name in local_map.items():
                val = tv_raw_inputs.get(tv_id)
                if val is not None and py_name in sig.parameters:
                    py_kwargs[py_name] = val

    # Force the chart to load all available historical bars by scrolling
    # to the first bar and zooming out.  This ensures Python's computation
    # uses the same bar range as TV (essential for recursive indicators
    # like EMA, Wilder's RSI, MACD).
    await tv._eval("""
(function() {
    var model = TradingViewApi.chart().chartWidget().model();
    var ts = model.timeScale();
    ts.scrollToFirstBar();
    ts.zoom(-1000);
    return true;
})()
""")
    await asyncio.sleep(2)

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
        tv_values_by_ts[int(entry["timestamp"])] = entry.get("value")

    bars = await tv.get_ohlcv(summary=False)
    if not bars:
        raise ValueError(f"No OHLCV data returned for {symbol} {timeframe}")

    # Compute Python indicator on ALL bars so recursive/EMA indicators
    # have enough history to converge before the comparison window.
    timestamps = [b["timestamp"] for b in bars]
    raw = computer(bars, **py_kwargs)
    if isinstance(raw, dict):
        key_map = _PLOT_KEY_MAP.get(study_id, {})
        tv_plot_name = plots[plot_index]["name"] if plot_index < len(plots) else ""
        py_key = key_map.get(tv_plot_name, list(raw.keys())[plot_index] if plot_index < len(raw) else list(raw.keys())[0])
        py_values = raw[py_key]
    else:
        py_values = raw

    # Determine comparison window: skip warmup (None) and clamp to max_bars
    min_idx = 0
    while min_idx < len(py_values) and py_values[min_idx] is None:
        min_idx += 1

    compare_start = 0
    if max_bars is not None and len(bars) > max_bars:
        compare_start = len(bars) - max_bars
    if compare_start < min_idx:
        compare_start = min_idx

    mismatches: list[Mismatch] = []
    matched = 0

    for i in range(compare_start, len(bars)):
        ts = int(timestamps[i])
        py_val = py_values[i]
        tv_val = tv_values_by_ts.get(ts)

        if py_val is None or tv_val is None:
            continue

        delta = abs(py_val - tv_val)
        if delta > tolerance:
            mismatches.append(Mismatch(ts, py_val, tv_val, delta))
        else:
            matched += 1

    total = len(bars) - compare_start
    return ParityReport(
        symbol=symbol,
        timeframe=timeframe,
        indicator=indicator,
        total_bars=total,
        matched=matched,
        mismatches=mismatches,
        tolerance=tolerance,
    )
