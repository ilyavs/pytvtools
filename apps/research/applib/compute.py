"""Indicator computation and chart building."""

from __future__ import annotations

from typing import Any

from pytvtools_core.chart import Chart
from pytvtools_core.indicators import sma, ema, rsi, atr, bbands, macd


COLORS = [
    "#FFA600", "#4E5185", "#00BFFF", "#FF6B6B", "#50C878",
    "#FF69B4", "#9370DB", "#20B2AA", "#FF8C00", "#7FFF00",
]


def _next_color(idx: int) -> str:
    return COLORS[idx % len(COLORS)]


def compute_indicators(
    bars: list[dict[str, Any]],
    selected: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Compute indicators from *selected* config.

    *selected* maps ``indicator_id -> {param_name: value}``.

    Keys like ``period_short`` / ``period_long`` create separate
    function calls (multiple lines per indicator).
    """
    groups: dict[str, list[dict[str, Any]]] = {
        "line": [],
        "histogram": [],
        "area": [],
        "baseline": [],
    }
    color_idx = 0

    # ── SMA / EMA: one call per period value ──────────────────────
    for ind_id in ("sma", "ema"):
        if ind_id not in selected:
            continue
        fn = sma if ind_id == "sma" else ema
        params = selected[ind_id]
        for key in ("period_short", "period_long"):
            period = params.get(key)
            if period is None:
                continue
            result = fn(bars, period=int(period))
            c = _next_color(color_idx)
            color_idx += 1
            groups["line"].append({
                "name": f"{ind_id.upper()} {period}",
                "values": result,
                "color": c,
            })

    # ── RSI ───────────────────────────────────────────────────────
    if "rsi" in selected:
        period = int(selected["rsi"].get("period", 14))
        result = rsi(bars, period=period)
        groups["baseline"].append({
            "name": f"RSI {period}",
            "values": result,
            "color": _next_color(color_idx := color_idx + 1),
            "base_value": 50,
        })

    # ── ATR ───────────────────────────────────────────────────────
    if "atr" in selected:
        period = int(selected["atr"].get("period", 14))
        result = atr(bars, period=period)
        groups["line"].append({
            "name": f"ATR {period}",
            "values": result,
            "color": _next_color(color_idx := color_idx + 1),
        })

    # ── Bollinger Bands ───────────────────────────────────────────
    if "bbands" in selected:
        period = int(selected["bbands"].get("period", 20))
        stddev = float(selected["bbands"].get("stddev", 2.0))
        result = bbands(bars, period=period, stddev=stddev)
        c = _next_color(color_idx := color_idx + 1)
        if isinstance(result, dict):
            groups["area"].append({
                "name": "BB Upper",
                "values": result["upper"],
                "color": c,
                "top_color": "rgba(78,81,133,0.3)",
                "bottom_color": "rgba(78,81,133,0.05)",
            })
            groups["line"].append({
                "name": "BB Basis",
                "values": result["basis"],
                "color": c,
            })
            groups["area"].append({
                "name": "BB Lower",
                "values": result["lower"],
                "color": c,
                "top_color": "rgba(78,81,133,0.05)",
                "bottom_color": "rgba(78,81,133,0.3)",
            })

    # ── MACD ──────────────────────────────────────────────────────
    if "macd" in selected:
        fast = int(selected["macd"].get("fast", 12))
        slow = int(selected["macd"].get("slow", 26))
        signal = int(selected["macd"].get("signal", 9))
        result = macd(bars, fast=fast, slow=slow, signal=signal)
        if isinstance(result, dict):
            groups["line"].append({
                "name": "MACD",
                "values": result["macd"],
                "color": "#00BFFF",
            })
            groups["line"].append({
                "name": "Signal",
                "values": result["signal"],
                "color": "#FFA600",
            })
            groups["histogram"].append({
                "name": "MACD Hist",
                "values": result["histogram"],
                "color": "#FF6B6B",
            })

    return groups


def build_chart_html(
    bars: list[dict[str, Any]],
    indicator_groups: dict[str, list[dict[str, Any]]],
    timeframe: str = "1D",
) -> str:
    chart = Chart(
        width=1200,
        height=600,
        title=f"{bars[0].get('symbol', '')} — {timeframe}",
    )
    chart.set_candles(bars, timeframe=timeframe)

    for kind in ("area", "line", "baseline", "histogram"):
        add_map = {
            "line": chart.add_line,
            "histogram": chart.add_histogram,
            "area": chart.add_area,
            "baseline": chart.add_baseline,
        }
        for s in indicator_groups.get(kind, []):
            kwargs = dict(s)
            values = kwargs.pop("values")
            name = kwargs.pop("name", "")
            add_map[kind](values, name=name, **kwargs)

    return chart.render()
