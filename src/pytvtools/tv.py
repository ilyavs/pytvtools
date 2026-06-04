"""
High-level TradingView client — the main interface for all TV operations.

Usage:
    async with TV(port=9222) as tv:
        await tv.set_symbol("BTCUSD")
        data = await tv.get_ohlcv(count=100)
        studies = await tv.get_study_values()
"""
from __future__ import annotations

import json
import logging
from typing import Any

from pytvtools.cdp import CdpConnection, find_tv_target, make_ws_url, wait_for_cdp

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Known TV internal JS API paths (discovered via live probing)
# ---------------------------------------------------------------------------

_CHART_API = "window.TradingViewApi._activeChartWidgetWV.value()"
_CHART_COLLECTION = "window.TradingViewApi._chartWidgetCollection"
_REPLAY_API = "window.TradingViewApi._replayApi"
_ALERT_SERVICE = "window.TradingViewApi._alertService"
_BOTTOM_BAR = "window.TradingView.bottomWidgetBar"


# ---------------------------------------------------------------------------
# Helpers to build safe JS expressions
# ---------------------------------------------------------------------------


def _js_str(s: str) -> str:
    """Wrap a string for safe interpolation into JS."""
    return json.dumps(s)


def _chart_call(method: str, *args: Any) -> str:
    """Call a method on the chart widget: chart.symbol() etc."""
    a = ", ".join(json.dumps(a) for a in args)
    return f"({_CHART_API}.{method}({a}))"


def _chart_set(method: str, value: Any) -> str:
    return f"({_CHART_API}.{method}({json.dumps(value)})),Symbols !== 'undefined'"


# ---------------------------------------------------------------------------
# TV Client
# ---------------------------------------------------------------------------


class TV:
    """Primary client for talking to TradingView via CDP."""

    def __init__(self, port: int = 9222, target: dict[str, Any] | None = None):
        self.port = port
        self._target = target
        self._cdp: CdpConnection | None = None

    async def __aenter__(self) -> TV:
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.disconnect()

    async def connect(self) -> None:
        if not self._target:
            self._target = await find_tv_target(port=self.port)
        if not self._target:
            raise RuntimeError(
                "No TradingView chart tab found. "
                "Open https://www.tradingview.com/chart/ in Chrome."
            )
        ws_url = make_ws_url(self._target)
        self._cdp = CdpConnection(ws_url)
        await self._cdp.connect()

    async def disconnect(self) -> None:
        if self._cdp:
            await self._cdp.close()
            self._cdp = None

    # ------------------------------------------------------------------
    # Chart control
    # ------------------------------------------------------------------

    async def get_state(self) -> dict[str, Any]:
        js = f"""
        (function() {{
            var c = {_CHART_API};
            return {{
                symbol: c.symbol(),
                timeframe: c.resolution(),
                chartType: c.chartType(),
            }};
        }})()
        """
        return await self._eval(js)

    async def set_symbol(self, symbol: str) -> None:
        await self._eval(f"({_CHART_API}.setSymbol({_js_str(symbol)}))")

    async def set_timeframe(self, timeframe: str) -> None:
        await self._eval(f"({_CHART_API}.setResolution({_js_str(timeframe)}))")

    async def set_chart_type(self, chart_type: int | str) -> None:
        await self._eval(_chart_call("setChartType", chart_type))

    async def scroll_to_date(self, date: str) -> None:
        await self._eval(f"({_CHART_API}.scrollToDate({_js_str(date)}))")

    async def get_visible_range(self) -> dict[str, Any]:
        return await self._eval(f"""
        (function() {{
            var r = {_CHART_API}.timeRange();
            if (r) return {{from: r.from, to: r.to}};
            return null;
        }})()
        """)

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    async def get_ohlcv(self, count: int = 500, summary: bool = False) -> Any:
        js = f"""
        (function() {{
            var bars = {_CHART_API}._chartWidget.model().mainSeries().bars();
            var all = bars().slice(-{count});
            if ({str(summary).lower()}) {{
                var highs = all.map(function(b) {{ return b.high; }});
                var lows = all.map(function(b) {{ return b.low; }});
                var closes = all.map(function(b) {{ return b.close; }});
                return {{
                    count: all.length,
                    high: Math.max.apply(null, highs),
                    low: Math.min.apply(null, lows),
                    open: all[0].open,
                    close: closes[closes.length - 1],
                    avg_volume: Math.round(all.reduce(function(s,b) {{ return s + b.volume; }}, 0) / all.length),
                    range: (Math.max.apply(null, highs) - Math.min.apply(null, lows)).toFixed(2)
                }};
            }}
            return all.map(function(b) {{
                return {{
                    timestamp: b.time,
                    open: b.open,
                    high: b.high,
                    low: b.low,
                    close: b.close,
                    volume: b.volume
                }};
            }});
        }})()
        """
        return await self._eval(js)

    async def get_quote(self, symbol: str | None = None) -> dict[str, Any]:
        return await self._eval(f"""
        (function() {{
            var q = window.TradingViewApi._activeChartWidgetWV.value();
            var s = q.symbol();
            var quotes = q.quotes();
            if (quotes && quotes[s]) return quotes[s];
            return {{ symbol: s }};
        }})()
        """)

    async def get_study_values(self) -> dict[str, Any]:
        """Read current values from ALL visible indicator studies."""
        return await self._eval("""
        (function() {
            var c = window.TradingViewApi._activeChartWidgetWV.value();
            var studies = c.getAllStudies() || [];
            var result = {};
            studies.forEach(function(s) {
                try {
                    var vals = c.chartWidget().activeChart().study(s.id).getAllStudiesValues();
                    result[s.name] = vals;
                } catch(e) {
                    result[s.name] = {error: e.message};
                }
            });
            return result;
        })()
        """)

    # ------------------------------------------------------------------
    # Indicators
    # ------------------------------------------------------------------

    async def add_indicator(
        self, name: str, inputs: dict[str, Any] | None = None
    ) -> None:
        """Add an indicator by full name (e.g. 'Relative Strength Index')."""
        expr = f"window.TradingViewApi._addIndicatorToChart({_js_str(name)})"
        if inputs:
            expr = f"(function(){{ {expr}; setTimeout(function(){{ /* set inputs */ }}, 500); }})()"
        await self._eval(expr)

    async def remove_indicator(self, entity_id: str) -> None:
        await self._eval(f"""
        (function() {{
            var c = {_CHART_API};
            c.chartWidget().activeChart().removeEntity({_js_str(entity_id)});
        }})()
        """)

    # ------------------------------------------------------------------
    # Pine Script
    # ------------------------------------------------------------------

    async def pine_set_source(self, source: str) -> None:
        """Inject source into the Pine editor."""
        escaped = source.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
        await self._eval(f"""
        (function() {{
            var el = document.querySelector('.monaco-editor textarea');
            if (!el) throw new Error('Pine editor not open');
            el.focus();
            el.select();
            document.execCommand('insertText', false, `{escaped}`);
        }})()
        """)

    async def pine_compile(self) -> dict[str, Any]:
        """Click the compile button and return errors (if any)."""
        await self._ui_click("compile_errors")
        # Wait briefly for compilation
        import asyncio
        await asyncio.sleep(1)
        errors = await self._eval("""
        (function() {
            var els = document.querySelectorAll('.monaco-editor .error, .monaco-editor .warning');
            return Array.from(els).map(function(e) { return e.textContent; });
        })()
        """)
        return {"errors": errors}

    # ------------------------------------------------------------------
    # Drawings (Pine lines/labels/tables/boxes)
    # ------------------------------------------------------------------

    async def get_pine_lines(
        self, study_filter: str | None = None
    ) -> list[dict[str, Any]]:
        js = """
        (function() {
            var c = window.TradingViewApi._activeChartWidgetWV.value();
            var lines = c.chartWidget().activeChart().getAllLines() || [];
            var result = [];
            lines.forEach(function(l) {
                result.push({id: l.id, price: l.price, text: l.text || ''});
            });
            return result;
        })()
        """
        raw = await self._eval(js) or []
        if study_filter:
            raw = [l for l in raw if study_filter.lower() in l.get("text", "").lower()]
        return raw

    async def get_pine_labels(
        self, study_filter: str | None = None, max_labels: int = 50
    ) -> list[dict[str, Any]]:
        js = f"""
        (function() {{
            var labels = window.TradingViewApi._activeChartWidgetWV.value()
                .chartWidget().activeChart().getAllLabels() || [];
            return labels.slice(0, {max_labels}).map(function(l) {{
                return {{text: l.text || '', price: l.price, time: l.time}};
            }});
        }})()
        """
        raw = await self._eval(js) or []
        if study_filter:
            raw = [l for l in raw if study_filter.lower() in l.get("text", "").lower()]
        return raw

    # ------------------------------------------------------------------
    # Screenshot
    # ------------------------------------------------------------------

    async def capture_screenshot(self, region: str = "chart") -> str:
        """Returns base64-encoded PNG."""
        if not self._cdp:
            raise RuntimeError("Not connected")
        result = await self._cdp._send(
            "Page.captureScreenshot",
            {"format": "png", "fromSurface": True},
        )
        return result.get("data", "")

    # ------------------------------------------------------------------
    # Batch
    # ------------------------------------------------------------------

    async def batch(
        self, symbols: list[str], timeframes: list[str], action: str = "ohlcv"
    ) -> dict[str, Any]:
        """Iterate symbols/timeframes and collect data."""
        results = {}
        for sym in symbols:
            await self.set_symbol(sym)
            import asyncio

            await asyncio.sleep(0.3)
            sym_data = {}
            for tf in timeframes:
                await self.set_timeframe(tf)
                await asyncio.sleep(0.2)
                if action == "ohlcv":
                    sym_data[tf] = await self.get_ohlcv(summary=True)
                elif action == "studies":
                    sym_data[tf] = await self.get_study_values()
            results[sym] = sym_data
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _eval(self, expression: str) -> Any:
        if not self._cdp:
            raise RuntimeError("Not connected. Call connect() first.")
        return await self._cdp.evaluate(expression)

    async def _ui_click(self, label: str) -> None:
        """Click a UI button by text/aria label."""
        await self._eval(f"""
        (function() {{
            var btns = document.querySelectorAll('button');
            for (var i = 0; i < btns.length; i++) {{
                var b = btns[i];
                if (b.textContent.trim() === {_js_str(label)} ||
                    b.getAttribute('aria-label') === {_js_str(label)}) {{
                    b.click();
                    return;
                }}
            }}
            throw new Error('Button not found: ' + {_js_str(label)});
        }})()
        """)
