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
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from pytvtools_core.indicators import rsi, sma, ema, macd, mfi, bbands, atr, srsi, supertrend, dss, market_cipher_b, pvp
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
    load_all_bars: bool = True,
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
    load_all_bars : bool
        If ``True``, scroll the chart to the first bar to force loading all
        historical data (needed for recursive indicators like EMA, RSI).
        Set ``False`` for indicators that only need recent bars (e.g. PVP).
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
    # like EMA, Wilder's RSI, MACD).  Set load_all_bars=False for indicators
    # that only need recent bars (e.g. PVP).
    if load_all_bars:
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


async def _wait_for_indicator_data(
    tv: TV, entity_id: str, max_retries: int = 20, delay: float = 0.5
) -> dict | None:
    """Poll ``get_indicator_data`` until data arrives."""
    for _ in range(max_retries):
        data = await tv.get_indicator_data(entity_id)
        if data and data.get("plots") and data["count"] > 0:
            return data
        await asyncio.sleep(delay)
    return None


def _ts_to_date(ts: int) -> str:
    """Convert unix timestamp to YYYY-MM-DD string."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _save_pvp_debug(
    path: str,
    symbol: str,
    timeframe: str,
    marker_tss: list[int],
    df: pd.DataFrame,
) -> None:
    """Write a detailed PVP comparison report (mirrors pvp_comparison_data.txt format)."""
    lines: list[str] = []
    sep = "=" * 100
    sub = "-" * 100

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines.append(sep)
    lines.append("PERIODIC VOLUME PROFILE — POSITIONAL LINE-TO-PERIOD MAPPING")
    lines.append(sep)
    lines.append(f"Symbol:        {symbol}")
    lines.append(f"Timeframe:     {timeframe}")
    lines.append(f"Generated:     {now_str}")
    lines.append("")

    markers_shown = min(len(marker_tss), 60)
    N = len(df)
    lines.append(f"Period markers:     {len(marker_tss)} ({len(marker_tss)} total)")
    lines.append(f"Visible POC lines:  {N} (from _primitivesDataById, TV ~50 cap)")
    lines.append(f"Mapped periods:     {N} (last {N + 1} markers → {N} periods)")
    lines.append("")
    lines.append("Method: Each line.new() is created at a Period Marker bar (is_new_period).")
    lines.append("        The line's POC price represents the COMPLETED period since the")
    lines.append("        previous marker. Line[k] ↔ period marker[-(N+1)+k].")
    lines.append("")
    lines.append(f"Last {markers_shown} markers (oldest to newest):")
    for i in range(markers_shown):
        ts = marker_tss[-(markers_shown) + i]
        lines.append(f"  marker[{i}]: {_ts_to_date(ts)} (ts={ts})")
    lines.append("")

    lines.append(sub)
    matched = df["match"].sum()
    total = len(df)
    lines.append(f"COMPARISON — Custom POC vs Built-in POC at period end ({int(matched)}/{total} matched)")
    lines.append(sub)
    lines.append(f"{'Line ID':<8} {'Period':<28} {'Custom POC':<12} {'Built-in POC':<14} {'Delta':<10} {'Delta%':<10} {'Match':<6}")
    lines.append(sub)

    for _, row in df.iterrows():
        period_str = f"{row['period_start']} -> {row['period_end']}"
        mark = "✓" if row["match"] else "✗"
        pct_str = f"{row['delta_pct']:<8.4f}%"
        lines.append(
            f"{int(row['line_id']):<8} {period_str:<28} {row['custom_poc']:<12.4f} "
            f"{row['builtin_poc']:<14.4f} {row['delta']:<10.4f} {pct_str:<10} {mark:<5}"
        )

    lines.append("")
    lines.append(f"Match rate: {matched / total * 100:.1f}% ({int(matched)}/{total}) within ±0.01 tolerance")
    lines.append("")

    matched_rows = df[df["match"]]
    if len(matched_rows) > 0:
        lines.append("Matched periods:")
        for _, row in matched_rows.iterrows():
            lines.append(
                f"  {row['period_start']} -> {row['period_end']}: "
                f"custom={row['custom_poc']:.4f} builtin={row['builtin_poc']:.4f} "
                f"delta={row['delta']:.4f} ({row['delta_pct']:.4f}%)"
            )
        lines.append("")

    mismatch_rows = df[~df["match"]]
    if len(mismatch_rows) > 0:
        lines.append("Mismatches:")
        for _, row in mismatch_rows.iterrows():
            lines.append(
                f"  {row['period_start']} -> {row['period_end']}: "
                f"custom={row['custom_poc']:.4f} builtin={row['builtin_poc']:.4f} "
                f"delta={row['delta']:.4f} ({row['delta_pct']:.4f}%)"
            )
        lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info("PVP debug report saved to %s", path)


async def compare_pvp(
    tv: TV,
    symbol: str,
    timeframe: str = "60",
    *,
    period_unit: str = "Day",
    period_mult: int = 1,
    tolerance: float = 0.01,
    debug_path: str | None = None,
) -> dict:
    """Compare custom Pine PVP against built-in Periodic Volume Profile.

    Adds both indicators, then uses the **custom PVP's ``Period Marker`` plot** to
    determine exact period boundaries (no heuristic gap detection). The built-in
    PVP's ``Developing POC`` at the last bar of each period gives the completed-period
    POC. The custom PVP's completed-period POCs are read via ``get_pine_lines()``
    with ``sort_by="id"``, which returns visible ``line.new`` objects in
    chronological order (oldest visible first). Lines are positionally matched
    to periods: the N visible lines correspond to the last N completed periods,
    each bounded by two consecutive period markers.

    Parameters
    ----------
    tv : TV
        Connected TV instance.
    symbol : str
        Symbol to use (e.g. ``"BATS:INTC"``).
    timeframe : str
        Chart timeframe (e.g. ``"60"`` for 60m).
    tolerance : float
        Max absolute price difference for a match (default 0.01).
    debug_path : str, optional
        If provided, saves a detailed comparison text file to this path.

    Returns
    -------
    dict with keys: symbol, timeframe, matched, total, match_rate, mismatches,
    pvp_df (pandas.DataFrame)
    """
    from pytvtools.pine_parity import get_pine_indicator_source

    await tv.set_symbol(symbol)
    await tv.set_timeframe(timeframe)
    await tv.wait_for_chart_ready(timeout=10)
    await tv.remove_all_indicators()
    await asyncio.sleep(1)

    # --- Load max history (scroll to first bar, zoom out) ---
    await tv._eval("""
(function() {
    var ts = window.TradingViewApi.chart().chartWidget().model().timeScale();
    ts.scrollToFirstBar();
    for (var i = 0; i < 8; i++) ts.zoom(-2000);
    return '';
})()
""")
    await asyncio.sleep(5)

    # --- Add built-in PVP, then match its period to the custom PVP ---
    eid_builtin = await tv.add_indicator(
        "Periodic Volume Profile",
        inputs={"volume": "Total", "period": period_unit},
    )
    if eid_builtin is None:
        raise RuntimeError("Failed to add built-in Periodic Volume Profile")

    builtin_data = await _wait_for_indicator_data(tv, eid_builtin)
    if builtin_data is None:
        raise RuntimeError("No data returned for built-in PVP")

    builtin_poc_by_ts: dict[int, float] = {}
    for entry in builtin_data["plots"][0]["values"]:
        val = entry.get("value")
        if val is not None:
            builtin_poc_by_ts[int(entry["timestamp"])] = val

    # --- Add custom PVP via pine-facade (bypasses Pine Editor issues) ---
    # Use a unique name each time — save/new with allow_overwrite=true
    # reuses the cached compiled script when the name matches an existing one.
    source = get_pine_indicator_source("pvp")
    source = source.replace(
        'period_mult   = input.int(1, "Period Multiplier", group="Period")',
        f'period_mult   = input.int({period_mult}, "Period Multiplier", group="Period")',
    )
    source = source.replace(
        'period_unit   = input.string("Day", "Period Unit", options=["Day", "Week", "Month"], group="Period")',
        f'period_unit   = input.string("{period_unit}", "Period Unit", options=["Day", "Week", "Month"], group="Period")',
    )
    custom_script_name = f"PVP_Custom_{int(asyncio.get_event_loop().time())}"
    custom_eid = await tv.pine_facade_deploy(source, name=custom_script_name)
    await asyncio.sleep(3)

    # Wait for custom Period Marker data
    custom_data = await _wait_for_indicator_data(tv, custom_eid)
    if custom_data is None:
        raise RuntimeError("No data returned for custom PVP (Period Marker)")

    # Period Marker fires 1.0 at the first bar of each new period
    marker_tss = sorted(set(
        int(entry["timestamp"])
        for entry in custom_data["plots"][0]["values"]
        if entry.get("value") == 1
    ))
    if len(marker_tss) < 2:
        raise RuntimeError(
            f"Expected at least 2 period markers, got {len(marker_tss)}"
        )

    # --- Get custom PVP visible POC lines in chronological order ---
    lines = await tv.get_pine_lines(study_filter="PVP_Custom", sort_by="id")
    N = len(lines)
    if N == 0:
        raise RuntimeError("No visible POC lines found for custom PVP")

    # TV renders at most ~55 line.new per indicator.  Clamp to the number of
    # completed periods we actually have markers for.
    n_periods = min(N, len(marker_tss) - 1)

    # --- Positional matching ---
    # A line is created at marker[i+1] (when is_new_period fires).
    # It represents the period [marker[i], marker[i+1]].
    # When N > n_periods (extra visible lines beyond available markers),
    # skip the oldest ones: line[offset + k] ↔ marker[-(n+1)+k].
    offset = N - n_periods
    rows: list[dict] = []
    matched = 0

    for k in range(n_periods):
        period_start_ts = marker_tss[-(n_periods + 1) + k]
        period_end_ts = marker_tss[-(n_periods + 1) + k + 1]
        line = lines[offset + k]
        custom_poc = round(line["price"], 4)

        # Built-in POC at last bar before period end
        bar_tss = sorted(t for t in builtin_poc_by_ts if t < period_end_ts)
        if not bar_tss:
            continue
        builtin_poc = round(builtin_poc_by_ts[bar_tss[-1]], 4)

        delta = round(abs(builtin_poc - custom_poc), 4)
        is_match = delta <= tolerance
        if is_match:
            matched += 1

        builtin_poc_clean = builtin_poc if builtin_poc and builtin_poc != 0 else 1e-10
        delta_pct = round(delta / abs(builtin_poc_clean) * 100, 4)

        rows.append({
            "line_id": int(line["id"]),
            "period_start": _ts_to_date(period_start_ts),
            "period_start_ts": period_start_ts,
            "period_end": _ts_to_date(period_end_ts),
            "period_end_ts": period_end_ts,
            "custom_poc": custom_poc,
            "builtin_poc": builtin_poc,
            "delta": delta,
            "delta_pct": delta_pct,
            "match": is_match,
        })

    pvp_df = pd.DataFrame(rows)
    total = len(pvp_df)
    match_rate = (matched / total * 100) if total > 0 else 0.0
    mismatches = pvp_df[~pvp_df["match"]].to_dict("records")

    if debug_path:
        _save_pvp_debug(debug_path, symbol, timeframe, marker_tss, pvp_df)

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "matched": matched,
        "total": total,
        "match_rate": match_rate,
        "mismatches": mismatches,
        "pvp_df": pvp_df,
    }
