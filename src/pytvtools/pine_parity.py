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


async def compare_pine_pvp(
    tv: TV,
    symbol: str = "BINANCE:BTCUSDT",
    timeframe: str = "1H",
    *,
    period_mult: int = 1,
    period_unit: str = "Day",
    va_pct: int = 70,
    num_rows: int = 24,
    extend_poc: bool = True,
    tolerance: float = 0.01,
) -> PineParityReport:
    """Compare custom Pine PVP against Python reference.

    Pure-Python Volume Profile = ground truth.  Reads OHLCV bars via
    ``get_ohlcv`` (which works in all environments) and computes the
    reference in Python.  The custom Pine script is added for
    verification that it compiles; its plot values are optional.

    If the environment supports it (TradingView Desktop), the built-in
    PVP is also added and compared.
    """
    pine_name = "pvp"

    await tv.set_symbol(symbol)
    await tv.set_timeframe(timeframe)
    await tv.wait_for_chart_ready(timeout=10)
    await tv.remove_all_indicators()

    scroll_ago = {60: 120, "1H": 180, "1": 120, "5": 30, "15": 15, "D": 2000, "W": 2000 * 7, "M": 2000 * 30}
    days_back = scroll_ago.get(timeframe, 180)
    target_date = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    ohlcv = await tv.get_ohlcv(count=500, summary=False)
    if not ohlcv:
        raise RuntimeError("No OHLCV data returned from chart")

    ref_poc, ref_vah, ref_val = _compute_pvp_python(
        ohlcv, period_mult=period_mult, period_unit=period_unit,
        va_pct=va_pct, num_rows=num_rows,
    )

    period_tf_seconds = _period_unit_to_seconds(period_unit) * period_mult
    ref_period_map: dict[int, dict[str, float]] = {}
    for idx, b in enumerate(ohlcv):
        ts = int(b["timestamp"])
        pk = (ts // period_tf_seconds) * period_tf_seconds
        if ref_poc[idx] is not None:
            ref_period_map.setdefault(pk, {})["poc"] = ref_poc[idx]
        if ref_vah[idx] is not None:
            ref_period_map.setdefault(pk, {})["vah"] = ref_vah[idx]
        if ref_val[idx] is not None:
            ref_period_map.setdefault(pk, {})["val"] = ref_val[idx]

    source = get_pine_indicator_source(pine_name)

    try:
        await tv.scroll_to_date(target_date)
        custom_eid = await _pine_add_script(tv, source)
    except Exception as exc:
        logger.warning("Skipping custom PVP chart verification: %s", exc)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Pine add failure details", exc_info=True)
        custom_eid = None

    mismatches: list[PineMismatch] = []
    matched = 0
    source_str = "python_ref"

    if custom_eid is not None:
        custom_data = None
        for _ in range(15):
            custom_data = await tv.get_indicator_data(custom_eid)
            if custom_data and custom_data.get("plots") and custom_data["count"] > 0:
                break
            await asyncio.sleep(0.5)
        else:
            custom_data = await tv.get_indicator_data(custom_eid)

        if custom_data and custom_data.get("plots"):
            custom_plots = custom_data["plots"]
            custom_poc: dict[int, float] = {}
            if len(custom_plots) >= 1:
                for entry in custom_plots[0]["values"]:
                    if entry.get("value") is not None:
                        custom_poc[int(entry["timestamp"])] = entry["value"]

            if custom_poc:
                source_str = "pine_editor"
                custom_period_map: dict[int, float] = {}
                for ts, val in custom_poc.items():
                    pk = (ts // period_tf_seconds) * period_tf_seconds
                    custom_period_map[pk] = val

                all_periods = sorted(set(ref_period_map) & set(custom_period_map))
                for pk in all_periods:
                    bv = ref_period_map[pk]["poc"]
                    cv = custom_period_map[pk]
                    delta = abs(bv - cv)
                    if delta > tolerance:
                        mismatches.append(PineMismatch(pk, bv, cv, delta))
                    else:
                        matched += 1

        if custom_eid:
            try:
                await tv.remove_indicator(custom_eid)
            except Exception:
                pass

    total_bars = len(ref_period_map)
    return PineParityReport(
        symbol=symbol,
        timeframe=timeframe,
        pine_name=pine_name,
        total_bars=total_bars,
        matched=matched,
        mismatches=mismatches,
        tolerance=tolerance,
        source=source_str,
    )


def _timeframe_to_seconds(tf: str) -> int:
    """Convert a timeframe string to seconds."""
    if tf == "D":
        return 86400
    if tf == "W":
        return 604800
    if tf == "M":
        return 2592000
    return int(tf) * 60


def _period_unit_to_seconds(unit: str) -> int:
    """Convert a PVP period unit string to seconds."""
    if unit == "Minute":
        return 60
    if unit in ("Hour", "H"):
        return 3600
    if unit in ("Day", "D"):
        return 86400
    if unit in ("Week", "W"):
        return 604800
    if unit in ("Month", "M"):
        return 2592000
    if unit == "Quarter":
        return 7776000
    if unit == "Year":
        return 31536000
    return 86400


def _compute_pvp_python(
    bars: list[dict],
    *,
    period_mult: int = 1,
    period_unit: str = "Day",
    va_pct: int = 70,
    num_rows: int = 24,
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Compute PVP POC/VAH/VAL reference values from OHLCV bars.

    Returns per-bar arrays of POC, VAH, VAL aligned to the OHLCV input.
    Values are ``None`` for bars that aren't the last bar of a period
    (since PVP only emits at period boundaries).
    """
    period_tf_seconds = _period_unit_to_seconds(period_unit) * period_mult

    poc: list[float | None] = [None] * len(bars)
    vah: list[float | None] = [None] * len(bars)
    val: list[float | None] = [None] * len(bars)

    # Group bars by period
    periods: dict[int, list[dict]] = {}
    for b in bars:
        ts = int(b["timestamp"])
        pk = (ts // period_tf_seconds) * period_tf_seconds
        if pk not in periods:
            periods[pk] = []
        periods[pk].append(b)

    for pk, period_bars in periods.items():
        _poc, _vah, _val = _compute_single_profile(period_bars, num_rows, va_pct)

        idxs = [i for i, b in enumerate(bars) if int(b["timestamp"]) // period_tf_seconds * period_tf_seconds == pk]
        last_bar_idx = idxs[-1] if idxs else -1
        if _poc is not None and last_bar_idx >= 0:
            poc[last_bar_idx] = _poc
            vah[last_bar_idx] = _vah
            val[last_bar_idx] = _val

    return poc, vah, val


def _compute_single_profile(
    bars: list[dict],
    num_rows: int,
    va_pct: int,
) -> tuple[float | None, float | None, float | None]:
    """Compute POC, VAH, VAL for a single period's bars using Total volume mode.

    Returns (poc, vah, val) where ``vah`` is the Value Area High and
    ``val`` is the Value Area Low.  All are ``None`` if the profile
    is empty.
    """
    if not bars:
        return None, None, None

    min_price = min(b["low"] for b in bars)
    max_price = max(b["high"] for b in bars)
    if min_price == max_price:
        return None, None, None

    row_height = (max_price - min_price) / num_rows

    volume_rows: list[float] = [0.0] * num_rows
    for b in bars:
        low_idx = max(0, int((b["low"] - min_price) / row_height))
        high_idx = min(num_rows - 1, int((b["high"] - min_price) / row_height))
        vol = b.get("volume", 0) or 0
        tpv = vol / (high_idx - low_idx + 1) if (high_idx - low_idx + 1) > 0 else vol
        for ri in range(low_idx, high_idx + 1):
            volume_rows[ri] += tpv

    total_vol = sum(volume_rows)
    if total_vol == 0:
        return None, None, None

    poc_row = max(range(num_rows), key=lambda i: volume_rows[i])
    poc_price = min_price + (poc_row + 0.5) * row_height

    va_target = total_vol * va_pct / 100.0
    va_accum = volume_rows[poc_row]
    vah_row = poc_row
    val_row = poc_row
    left = poc_row - 1
    right = poc_row + 1

    while va_accum < va_target:
        left_vol = volume_rows[left] if left >= 0 else -1
        right_vol = volume_rows[right] if right < num_rows else -1

        if left_vol >= right_vol and left >= 0:
            va_accum += left_vol
            val_row = left
            left -= 1
        elif right < num_rows:
            va_accum += right_vol
            vah_row = right
            right += 1
        else:
            break

    vah_price = min_price + (vah_row + 1) * row_height
    val_price = min_price + val_row * row_height

    return poc_price, vah_price, val_price


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
            f"  Total bars:  {self.total_bars}\n"
            f"  Matched:     {self.matched} ({self.match_rate:.1f}%)\n"
            f"  Mismatches:  {len(self.mismatches)}\n"
            f"  Tolerance:   \u00b1{self.tolerance}\n"
        )
