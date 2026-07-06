"""Compare TradingView built-in indicators against reference implementations.

Pine parity compares a TradingView built-in indicator's computed values against
a reference implementation (Python by default).  For indicators that have a
Pine Script source in ``pine_indicators/``, it verifies the Pine logic matches
the built-in behaviour.

Usage::

    from pytvtools import TV
    from pytvtools.pine_parity import compare_pine_indicator

    async with TV() as tv:
        report = await compare_pine_indicator(tv, "NASDAQ:AAPL", "1D", "rsi")
        print(report.summary())
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
import time as _time
from pathlib import Path
from typing import Any

from pytvtools.indicator_parity import compare_indicator as _compare_py_indicator
from pytvtools.tv import TV
from pytvtools_core.indicators import pvp as _pvp_py
from pytvtools_core.indicators import _compute_period_poc

logger = logging.getLogger(__name__)

_PINE_DIR = Path(__file__).resolve().parent.parent.parent / "pine_indicators"

_PINE_INDICATORS: dict[str, dict[str, Any]] = {
    "rsi": {
        "file": "rsi.pine",
        "study_id": "STD;RSI",
        "plot_index": 0,
    },
    "sma": {
        "file": "sma.pine",
        "study_id": "STD;SMA",
        "plot_index": 0,
    },
    "ema": {
        "file": "ema.pine",
        "study_id": "STD;EMA",
        "plot_index": 0,
    },
    "macd": {
        "file": "macd.pine",
        "study_id": "STD;MACD",
        "plot_index": 2,
    },
    "mfi": {
        "file": "mfi.pine",
        "study_id": "STD;Money_Flow",
        "plot_index": 0,
    },
    "bbands": {
        "file": "bbands.pine",
        "study_id": "STD;Bollinger_Bands",
        "plot_index": 0,
    },
    "atr": {
        "file": "atr.pine",
        "study_id": "STD;Average_True_Range",
        "plot_index": 0,
    },
    "srsi": {
        "file": "srsi.pine",
        "study_id": "STD;Stochastic_RSI",
        "plot_index": 0,
    },
    "supertrend": {
        "file": "supertrend.pine",
        "study_id": "STD;Supertrend",
        "plot_index": 0,
    },
    "dss": {
        "file": "dss.pine",
        "study_id": "PUB;85",
        "plot_index": 0,
    },
    "pvp": {
        "file": "pvp.pine",
        "study_id": None,
        "plot_index": 0,
    },
}


class PineIndicatorNotFoundError(Exception):
    """Raised when the requested Pine indicator is not registered."""


class PineCompileError(Exception):
    """Raised when a Pine script fails to compile."""


class PineEntityNotFoundError(Exception):
    """Raised when the compiled Pine indicator can't be found on the chart."""


def get_pine_indicator_source(name: str) -> str:
    """Load the Pine Script source for a registered indicator by name."""
    info = _PINE_INDICATORS.get(name)
    if info is None:
        available = ", ".join(_PINE_INDICATORS)
        raise PineIndicatorNotFoundError(
            f"Unknown Pine indicator {name!r}. Available: {available}"
        )
    path = _PINE_DIR / info["file"]
    if not path.exists():
        raise FileNotFoundError(f"Pine indicator file not found: {path}")
    return path.read_text(encoding="utf-8")


async def _pine_add_script(tv: TV, source: str) -> str:
    """Open Pine editor, inject source, compile, and return entity ID.

    Handles both "Save and add to chart" (new study) and
    "Update on chart" (existing study recompiled).  In the update case
    the study ID is the same one that was already on the chart
    (from a previous compile).

    Raises ``PineEntityNotFoundError`` if the study can't be found.
    """
    studies_before = await tv._get_study_ids()

    await tv._eval("""
    (function() {
        var btn = document.querySelector('[data-name="pine-dialog-button"]');
        if (!btn) {
            var btns = document.querySelectorAll('button');
            for (var i = 0; i < btns.length; i++) {
                var aria = (btns[i].getAttribute('aria-label') || '').toLowerCase();
                var dname = (btns[i].getAttribute('data-name') || '').toLowerCase();
                if (aria.indexOf('pine') >= 0 || dname.indexOf('pine') >= 0) {
                    btn = btns[i];
                    break;
                }
            }
        }
        if (btn) {
            btn.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
        }
    })()
    """)
    await asyncio.sleep(3)

    await tv.pine_set_source(source)

    result = await tv.pine_compile()
    errors = result.get("errors", [])
    real_errors = [e for e in errors if isinstance(e, dict) and e.get("line") and e.get("severity", 0) >= 8]
    if real_errors:
        msg = "Pine script compilation failed:\n" + "\n".join(
            f"  Line {e.get('line','?')}: {e.get('message','')}"
            for e in real_errors
        )
        raise PineCompileError(msg)

    await asyncio.sleep(1.5)

    studies_after = await tv._get_study_ids()
    new_ids = [s for s in studies_after if s not in studies_before]
    if new_ids:
        return new_ids[0]

    # No new ID — the compile may have updated an existing study.
    # Use the last study ID from before (the editor's previous compile).
    if studies_before:
        return studies_before[-1]

    raise PineEntityNotFoundError(
        "No study entity found after Pine compile. "
        "This usually means you are not logged into TradingView "
        "(server-side compilation requires authentication)."
    )


async def compare_pine_indicator(
    tv: TV,
    symbol: str,
    timeframe: str,
    pine_name: str,
    *,
    max_bars: int | None = None,
    tolerance: float = 0.01,
    plot_index: int | None = None,
    use_pine_editor: bool = False,
) -> PineParityReport:
    """Compare a built-in TV indicator against its reference implementation.

    When *use_pine_editor* is ``True`` (requires authentication), the function
    injects the custom Pine Script source into the chart via the Pine Editor
    and reads the computed values directly.  By default (``False``) it uses
    the Python implementation as reference — this works without authentication
    and is significantly faster.

    Parameters
    ----------
    tv : TV
        Connected TV instance.
    symbol : str
        Symbol to use (e.g. ``"NASDAQ:AAPL"``).
    timeframe : str
        Timeframe string (e.g. ``"1D"``).
    pine_name : str
        Name of the registered Pine indicator (e.g. ``"rsi"``).
    max_bars : int | None
        Number of OHLCV bars to fetch.  ``None`` = all available.
    tolerance : float
        Maximum allowed absolute difference.
    plot_index : int | None
        Which plot to compare (``None`` = registered default).
    use_pine_editor : bool
        If ``True``, inject via the Pine Editor (requires auth).

    Returns
    -------
    PineParityReport
    """
    info = _PINE_INDICATORS.get(pine_name)
    if info is None:
        available = ", ".join(_PINE_INDICATORS)
        raise PineIndicatorNotFoundError(
            f"Unknown Pine indicator {pine_name!r}. Available: {available}"
        )

    study_id = info["study_id"]
    effective_plot = plot_index if plot_index is not None else info.get("plot_index", 0)

    if use_pine_editor:
        return await _compare_via_pine_editor(
            tv, symbol, timeframe, pine_name, study_id,
            source=get_pine_indicator_source(pine_name),
            max_bars=max_bars, tolerance=tolerance,
            plot_index=effective_plot,
        )

    return await _compare_via_python(
        tv, symbol, timeframe, pine_name, study_id,
        max_bars=max_bars, tolerance=tolerance,
        plot_index=effective_plot,
    )


def _lower_tf_for(chart_tf: str) -> str:
    """Match Pine's f_lower_tf() logic."""
    minutes = {"1": 1, "5": 5, "15": 15, "30": 30, "60": 60, "D": 1440, "W": 10080, "M": 43200}
    mins = minutes.get(str(chart_tf), int(chart_tf))
    if mins <= 15: return "1"
    if mins <= 30: return "5"
    if mins <= 60: return "10"
    if mins <= 120: return "15"
    if mins <= 240: return "30"
    return "60"


async def _detect_utc_offset_from_chart(tv: TV) -> float:
    """Detect the exchange's UTC offset from 60m chart bar timestamps.

    Reads the first chart bar's timestamp and determines the exchange
    timezone offset.  Assumes the last intra-day gap > 4 hours marks
    the overnight boundary, and that the first bar of each session is
    at 09:30 local time.
    """
    _CHART_API = "window.TradingViewApi.chart()"
    timestamps_sec = await tv._eval(f"""
    (function() {{
        var items = {_CHART_API}.chartWidget().model().mainSeries().bars()._items;
        if (!items || items.length === 0) return [];
        var limit = Math.min(items.length, 100);
        var start = Math.max(0, items.length - 200);
        var result = [];
        for (var i = start; i < start + limit && i < items.length; i++) {{
            result.push(items[i].value[0]);
        }}
        return result;
    }})()
    """)
    if not timestamps_sec:
        return 0.0

    ts = [int(t) for t in timestamps_sec]
    gaps = [(ts[i + 1] - ts[i]) for i in range(len(ts) - 1)]
    large_gaps = [(i, g) for i, g in enumerate(gaps) if g > 14400]

    if not large_gaps:
        return 0.0

    # First gap > 4 hours is overnight/weekend. The bar AFTER the gap
    # is the first bar of a trading day. For US equities with extended
    # hours that first bar is pre-market open at 04:00 local.
    # For regular-session-only charts it would be 09:30 local.
    # Detect which by checking if this gap occurs in a 04:00-09:00 window
    # (extended hours, first bar at 08:00-09:00 UTC = 04:00 local)
    # vs a 13:00-14:30 window (regular session, first bar at 13:30 UTC = 09:30 local).
    first_gap_idx = large_gaps[0][0]
    next_bar_ts = ts[first_gap_idx + 1]
    hour_utc = (next_bar_ts % 86400) / 3600.0

    if 8.0 <= hour_utc <= 9.0:
        # Extended hours: first bar is pre-market at 04:00 local
        offset = 4.0 - hour_utc
    elif 13.0 <= hour_utc <= 14.5:
        # Regular session only: first bar is 09:30 local
        offset = 9.5 - hour_utc
    else:
        return 0.0

    if abs(offset) > 14:
        return 0.0

    return offset


async def compare_pine_pvp(
    tv: TV,
    symbol: str = "BATS:GME",
    timeframe: str = "60",
    *,
    period_mult: int = 1,
    period_unit: str = "Day",
    num_rows: int = 24,
    tolerance: float = 0.01,
    utc_offset: float | None = None,
    ) -> PineParityReport:
    """Compare custom Pine PVP against Python reference.

    Deploys the custom Pine PVP script via the Pine Editor path, reads
    its ``line.new`` POC output via ``get_pine_lines()`` and its period
    markers via ``get_indicator_data()``, then compares on exact time
    intersection — each completed period's POC is computed on the LTF
    bars that fall within that period's marker boundaries.  Periods
    outside Python's LTF data range are skipped.

    Falls back to proximity matching when period markers are unavailable.

    Parameters
    ----------
    utc_offset : float, optional
        Hours from UTC (e.g. -5 for US Eastern Standard Time).
        If ``None`` (default), auto-detected from chart bar timestamps.

    Returns a ``PineParityReport`` with the number of overlapping periods
    matched within the given tolerance.
    """
    pine_name = "pvp"
    pine_deploy_name = f"PVP_{_time.time_ns()}"

    await tv.set_symbol(symbol)
    await tv.set_timeframe(timeframe)
    await tv.wait_for_chart_ready(timeout=10)
    await tv.remove_all_indicators()

    # Load max 60m history so Pine sees as many bars as possible
    await tv._eval("""
    (function() {
        var ts = window.TradingViewApi.chart().chartWidget().model().timeScale();
        ts.scrollToFirstBar();
        for (var i = 0; i < 8; i++) ts.zoom(-2000);
        return '';
    })()
    """)
    await asyncio.sleep(5)

    tick_size = await tv.get_tick_size()

    # Auto-detect UTC offset from 60m bar timestamps if not provided
    if utc_offset is None:
        utc_offset = await _detect_utc_offset_from_chart(tv)

    # Deploy custom Pine PVP with matching inputs
    source = get_pine_indicator_source(pine_name)
    # Override default inputs in the Pine source so the deployed indicator
    # matches the Python call (TV's set_indicator_inputs is unreliable)
    source = source.replace(
        'period_mult   = input.int(1, "Period Multiplier", group="Period")',
        f'period_mult   = input.int({period_mult}, "Period Multiplier", group="Period")',
    )
    source = source.replace(
        'period_unit   = input.string("Day", "Period Unit", options=["Day", "Week", "Month"], group="Period")',
        f'period_unit   = input.string("{period_unit}", "Period Unit", options=["Day", "Week", "Month"], group="Period")',
    )
    source = source.replace(
        'num_rows      = input.int(24, "Number of Rows", group="Rows", minval=1)',
        f'num_rows      = input.int({num_rows}, "Number of Rows", group="Rows", minval=1)',
    )
    try:
        custom_eid = await tv.pine_facade_deploy(source, name=pine_deploy_name)
    except Exception as exc:
        logger.warning("Skipping custom PVP chart verification: %s", exc)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Pine deploy failure details", exc_info=True)
        return PineParityReport(
            symbol=symbol, timeframe=timeframe, pine_name=pine_name,
            total_bars=0, matched=0, mismatches=[], tolerance=tolerance,
            source="deploy_failed",
        )

    await asyncio.sleep(5)

    # Read POC lines from Pine drawing primitives
    lines = await tv.get_pine_lines(study_filter="PVP_Custom", sort_by="id")
    if not lines:
        try:
            await tv.remove_indicator(custom_eid)
        except Exception:
            pass
        return PineParityReport(
            symbol=symbol, timeframe=timeframe, pine_name=pine_name,
            total_bars=0, matched=0, mismatches=[], tolerance=tolerance,
            source="no_lines",
        )

    pine_pocs = [l["price"] for l in lines]

    # Read period markers from indicator data (timestamps where
    # is_new_period fired).  These are the START of each period,
    # bar 0 has no marker (ta.change returns na).
    indicator_data = await tv.get_indicator_data(custom_eid)
    markers: list[int] = []
    if indicator_data and indicator_data.get("plots"):
        for plot in indicator_data["plots"]:
            if "Period Marker" in plot.get("name", ""):
                markers = sorted([
                    v["timestamp"] for v in plot["values"]
                    if v.get("value") and abs(v["value"] - 1.0) < 0.5
                ])
                break

    # Fetch lower-TF data by switching chart and forcing full history load
    ltf_tf = _lower_tf_for(timeframe)
    await tv.set_timeframe(ltf_tf)
    await asyncio.sleep(3)
    await tv._eval("""
    (function() {
        var ts = window.TradingViewApi.chart().chartWidget().model().timeScale();
        ts.scrollToFirstBar();
        for (var i = 0; i < 8; i++) ts.zoom(-2000);
        return '';
    })()
    """)
    await asyncio.sleep(8)
    ltf_bars = await tv.get_ohlcv(count=None, summary=False)

    # Restore original timeframe
    await tv.set_timeframe(timeframe)
    await asyncio.sleep(1)

    # Remove deployed indicator
    try:
        await tv.remove_indicator(custom_eid)
    except Exception:
        pass

    if not ltf_bars:
        return PineParityReport(
            symbol=symbol, timeframe=timeframe, pine_name=pine_name,
            total_bars=0, matched=0, mismatches=[], tolerance=tolerance,
            source="no_ltf_data",
        )

    ltf_first = ltf_bars[0]["timestamp"]
    ltf_last = ltf_bars[-1]["timestamp"]

    if not markers:
        # No period markers read — fallback: old proximity matching.
        py_pocs = sorted(
            v for v in _pvp_py(
                ltf_bars, period_mult=period_mult,
                period_unit=period_unit, num_rows=num_rows,
                mintick=tick_size, utc_offset=utc_offset,
            )
            if v is not None
        )
        n_py = len(py_pocs)
        n_overlap = min(n_py, len(pine_pocs))
        pine_to_match = pine_pocs[-n_overlap:] if n_overlap > 0 else []
        mismatches_fallback: list[PineMismatch] = []
        matched_fallback = 0
        used_fallback: set[int] = set()
        for pine_val in pine_to_match:
            diffs = [(abs(pine_val - pv), i) for i, pv in enumerate(py_pocs)]
            diffs.sort()
            best_diff, best_i = diffs[0]
            if best_diff <= tolerance and best_i not in used_fallback:
                matched_fallback += 1
                used_fallback.add(best_i)
            else:
                mismatches_fallback.append(PineMismatch(
                    0, py_pocs[best_i] if py_pocs else None, pine_val, best_diff,
                ))
        return PineParityReport(
            symbol=symbol, timeframe=timeframe, pine_name=pine_name,
            total_bars=n_overlap, matched=matched_fallback,
            mismatches=mismatches_fallback, tolerance=tolerance,
            source="pine_editor",
        )

    # Time-intersection matching.
    #
    # markers[0] fires at the start of period 1 (first time-unit change
    # after bar 0).  Period k (k=0,1,...,M-1) spans:
    #   start = markers[k-1] if k > 0 else ltf_bars[0].timestamp
    #   end   = markers[k]
    # POC_line[k] (in chronological order) is the POC for period k.
    #
    # TV renders at most ~50 line.new per indicator, so only the last
    # L = len(pine_pocs) periods have visible POC lines.  We align:
    #   pine_pocs[i]  →  period_idx = M - L + i
    #   (i=0 → oldest visible period, i=L-1 → most recent)
    M = len(markers)
    L = len(pine_pocs)
    assert M >= 2, f"Need at least 2 markers for one completed period, got {M}"

    mismatches_t: list[PineMismatch] = []
    matched_t = 0

    for i in range(L):
        period_idx = M - L + i
        if period_idx < 0:
            continue

        # Period boundaries from markers
        p_start = markers[period_idx - 1] if period_idx > 0 else ltf_first
        p_end = markers[period_idx]

        # Skip periods with no LTF overlap, or where Python's data
        # starts mid-period (partial data = inaccurate POC)
        if p_end <= ltf_first or p_start > ltf_last or p_start < ltf_first:
            continue

        # Filter LTF bars within this exact time window
        period_bars = [
            b for b in ltf_bars
            if p_start <= b["timestamp"] < p_end
        ]
        if not period_bars:
            continue

        # Compute Python POC on this period's LTF bars
        py_poc = _compute_period_poc(
            [float(b["high"]) for b in period_bars],
            [float(b["low"]) for b in period_bars],
            [float(b.get("volume", 0) or 0) for b in period_bars],
            num_rows=num_rows,
            mintick=tick_size,
        )
        if py_poc is None:
            continue

        pine_poc = pine_pocs[i]
        delta = abs(py_poc - pine_poc)
        if delta <= tolerance:
            matched_t += 1
        else:
            mismatches_t.append(PineMismatch(0, py_poc, pine_poc, delta))

    return PineParityReport(
        symbol=symbol,
        timeframe=timeframe,
        pine_name=pine_name,
        total_bars=matched_t + len(mismatches_t),
        matched=matched_t,
        mismatches=mismatches_t,
        tolerance=tolerance,
        source="pine_editor",
    )


async def _compare_via_python(
    tv: TV,
    symbol: str,
    timeframe: str,
    pine_name: str,
    study_id: str,
    *,
    max_bars: int | None,
    tolerance: float,
    plot_index: int,
) -> PineParityReport:
    """Compare built-in TV indicator vs Python reference implementation."""
    py_report = await _compare_py_indicator(
        tv, symbol, timeframe, study_id,
        max_bars=max_bars, tolerance=tolerance, plot_index=plot_index,
    )
    return PineParityReport(
        symbol=py_report.symbol,
        timeframe=py_report.timeframe,
        pine_name=pine_name,
        total_bars=py_report.total_bars,
        matched=py_report.matched,
        mismatches=[
            PineMismatch(m.timestamp, m.py_val, m.tv_val, m.delta)
            for m in py_report.mismatches
        ],
        tolerance=py_report.tolerance,
        source="python",
    )


async def _compare_via_pine_editor(
    tv: TV,
    symbol: str,
    timeframe: str,
    pine_name: str,
    study_id: str,
    *,
    source: str,
    max_bars: int | None,
    tolerance: float,
    plot_index: int,
) -> PineParityReport:
    """Inject Pine Script via the editor and compare against the built-in."""
    await tv.set_symbol(symbol)
    await tv.set_timeframe(timeframe)
    await tv.wait_for_chart_ready(timeout=10)

    # Force the chart to load all available historical bars by scrolling
    # to the first bar and zooming out.  This ensures both built-in and
    # custom indicator data sources are fully populated.
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

    # --- Built-in indicator ---
    eid_builtin = await tv.add_indicator(study_id)
    if eid_builtin is None:
        raise RuntimeError(f"Failed to add built-in indicator {study_id}")

    # Read built-in's actual input values to pass to the custom Pine
    builtin_inputs: dict[str, Any] = {}
    js = """
    (function() {
        var study = TradingViewApi.chart().getStudyById(__EID__);
        if (!study) return null;
        var vals = study.getInputValues ? study.getInputValues() : [];
        var r = {};
        vals.forEach(function(v) { r[v.id] = v.value; });
        return r;
    })()
    """.replace("__EID__", repr(eid_builtin))
    raw_inputs = await tv._eval(js)
    if raw_inputs and isinstance(raw_inputs, dict):
        builtin_inputs = raw_inputs

    for _ in range(15):
        builtin_data = await tv.get_indicator_data(eid_builtin)
        if builtin_data and builtin_data.get("plots") and builtin_data["count"] > 0:
            break
        await asyncio.sleep(0.5)
    else:
        builtin_data = await tv.get_indicator_data(eid_builtin)
    if builtin_data is None:
        raise RuntimeError(f"No data returned for built-in {study_id}")

    await tv.remove_indicator(eid_builtin)

    # --- Custom Pine indicator ---
    custom_eid = await _pine_add_script(tv, source)


    # Apply the same input values the built-in used.
    # Only pass inputs that the custom Pine indicator actually supports.
    if builtin_inputs:
        js2 = """
        (function() {
            var study = TradingViewApi.chart().getStudyById(__EID__);
            if (!study) return null;
            var vals = study.getInputValues ? study.getInputValues() : [];
            var r = {};
            vals.forEach(function(v) { r[v.id] = v.value; });
            return r;
        })()
        """.replace("__EID__", repr(custom_eid))
        custom_raw = await tv._eval(js2)
        if custom_raw and isinstance(custom_raw, dict):
            filtered = {k: v for k, v in builtin_inputs.items() if k in custom_raw}
            if filtered:
                await tv.set_indicator_inputs(custom_eid, filtered)
                await asyncio.sleep(0.5)

    for _ in range(15):
        custom_data = await tv.get_indicator_data(custom_eid)
        if custom_data and custom_data.get("plots") and custom_data["count"] > 0:
            break
        await asyncio.sleep(0.5)
    else:
        custom_data = await tv.get_indicator_data(custom_eid)
    if custom_data is None:
        raise RuntimeError(f"No data returned for custom Pine indicator {custom_eid}")

    await tv.remove_indicator(custom_eid)

    # --- Align and compare ---
    builtin_plots = builtin_data.get("plots", [])
    custom_plots = custom_data.get("plots", [])

    if plot_index >= len(builtin_plots):
        raise ValueError(
            f"Built-in plot index {plot_index} out of range "
            f"(only {len(builtin_plots)} plots available)"
        )
    if plot_index >= len(custom_plots):
        raise ValueError(
            f"Custom Pine plot index {plot_index} out of range "
            f"(only {len(custom_plots)} plots available)"
        )

    builtin_by_ts: dict[int, float | None] = {}
    for entry in builtin_plots[plot_index]["values"]:
        if "value" in entry:
            builtin_by_ts[int(entry["timestamp"])] = entry["value"]

    custom_by_ts: dict[int, float | None] = {}
    for entry in custom_plots[plot_index]["values"]:
        if "value" in entry:
            custom_by_ts[int(entry["timestamp"])] = entry["value"]

    # Build timestamp list from the union of both data sources
    all_tss = sorted(set(builtin_by_ts) | set(custom_by_ts))

    mismatches: list[PineMismatch] = []
    matched = 0

    first_valid = 0
    while first_valid < len(all_tss):
        ts = all_tss[first_valid]
        bv = builtin_by_ts.get(ts)
        cv = custom_by_ts.get(ts)
        if bv is not None and cv is not None:
            break
        first_valid += 1

    for i in range(first_valid, len(all_tss)):
        ts = all_tss[i]
        bv = builtin_by_ts.get(ts)
        cv = custom_by_ts.get(ts)
        if bv is None or cv is None:
            continue
        delta = abs(bv - cv)
        if delta > tolerance:
            mismatches.append(PineMismatch(ts, bv, cv, delta))
        else:
            matched += 1

    total = len(all_tss) - first_valid
    return PineParityReport(
        symbol=symbol,
        timeframe=timeframe,
        pine_name=pine_name,
        total_bars=total,
        matched=matched,
        mismatches=mismatches,
        tolerance=tolerance,
        source="pine_editor",
    )


class PineMismatch:
    """One bar where built-in and reference values disagree."""

    def __init__(self, timestamp: int, reference_val: float | None, tv_val: float | None, delta: float):
        self.timestamp = timestamp
        self.reference_val = reference_val
        self.tv_val = tv_val
        self.delta = delta

    def __repr__(self) -> str:
        return (
            f"PineMismatch(ts={self.timestamp}, ref={self.reference_val}, "
            f"tv={self.tv_val}, delta={self.delta:.6f})"
        )


class PineParityReport:
    """Result of comparing built-in TV indicator against a reference."""

    def __init__(
        self,
        symbol: str,
        timeframe: str,
        pine_name: str,
        total_bars: int,
        matched: int,
        mismatches: list[PineMismatch],
        tolerance: float,
        source: str = "python",
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.pine_name = pine_name
        self.total_bars = total_bars
        self.matched = matched
        self.mismatches = mismatches
        self.tolerance = tolerance
        self.source = source

    @property
    def match_rate(self) -> float:
        if self.total_bars == 0:
            return 0.0
        return self.matched / self.total_bars * 100

    def summary(self) -> str:
        if self.source == "python_ref":
            return (
                f"Pine parity: {self.pine_name} on {self.symbol} ({self.timeframe})\n"
                f"  Source:      python (verification-only)\n"
                f"  Periods:     {self.total_bars} (Python reference computed)\n"
                f"  Note:        Built-in PVP data unavailable in this environment;\n"
                f"               compare on TV Desktop for full parity\n"
            )
        return (
            f"Pine parity: {self.pine_name} on {self.symbol} ({self.timeframe})\n"
            f"  Source:      {self.source}\n"
            f"  Overlap:     {self.total_bars} periods\n"
            f"  Matched:     {self.matched} ({self.match_rate:.1f}%)\n"
            f"  Mismatches:  {len(self.mismatches)}\n"
            f"  Tolerance:   \u00b1{self.tolerance}\n"
        )
