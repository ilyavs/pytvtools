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
import logging
from pathlib import Path
from typing import Any

from pytvtools.indicator_parity import compare_indicator as _compare_py_indicator
from pytvtools.tv import TV

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
        if (btn) { btn.click(); return; }
        var btns = document.querySelectorAll('button');
        for (var i = 0; i < btns.length; i++) {
            var aria = (btns[i].getAttribute('aria-label') || '').toLowerCase();
            var dname = (btns[i].getAttribute('data-name') || '').toLowerCase();
            if (aria.indexOf('pine') >= 0 || dname.indexOf('pine') >= 0) {
                btn = btns[i];
                btn.click();
                return;
            }
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
        return (
            f"Pine parity: {self.pine_name} on {self.symbol} ({self.timeframe})\n"
            f"  Source:      {self.source}\n"
            f"  Total bars:  {self.total_bars}\n"
            f"  Matched:     {self.matched} ({self.match_rate:.1f}%)\n"
            f"  Mismatches:  {len(self.mismatches)}\n"
            f"  Tolerance:   \u00b1{self.tolerance}\n"
        )
