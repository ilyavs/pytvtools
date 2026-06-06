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

MAX_INDICATORS = 2


class TooManyIndicatorsError(RuntimeError):
    """Raised when adding an indicator would exceed MAX_INDICATORS."""


# ---------------------------------------------------------------------------
# Known TV internal JS API paths (discovered via live probing)
# ---------------------------------------------------------------------------

_CHART_API = "window.TradingViewApi.chart()"



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
        self._indicator_ids: set[str] = set()

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
        self._indicator_ids = set(await self._get_study_ids())

    async def get_indicator_count(self) -> int:
        """Return the number of studies currently on the chart."""
        return len(await self._get_study_ids())

    async def _get_study_ids(self) -> list[str]:
        ids = await self._eval(f"""
        (function() {{
            var studies = {_CHART_API}.getAllStudies() || [];
            return studies.map(function(s) {{ return s.id; }});
        }})()
        """)
        return ids or []

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
        await self._eval(f"""
        (function() {{
            var chart = {_CHART_API};
            var w = chart.chartWidget();
            var ac = w.activeChart ? w.activeChart() : null;
            if (ac && ac.scrollToDate) {{
                ac.scrollToDate({_js_str(date)});
            }} else if (w.scrollToDate) {{
                w.scrollToDate({_js_str(date)});
            }} else {{
                var ts = {_js_str(date)};
                if (typeof ts === 'string' && ts.indexOf('-') > 0) {{
                    ts = new Date(ts).getTime() / 1000;
                }}
                var model = w.model();
                var sr = model.mainSeries();
                if (sr && sr.setTimeScale) {{
                    sr.setTimeScale({{from: ts - 86400, to: ts + 86400}});
                }}
            }}
            return true;
        }})()
        """)

    async def get_visible_range(self) -> dict[str, Any]:
        return await self._eval(f"""
        (function() {{
            var model = {_CHART_API}.chartWidget().model();
            var sr = model.mainSeries().data();
            if (sr && sr.first() && sr.last()) {{
                var first = sr.first();
                var last = sr.last();
                return {{from: first.time, to: last.time}};
            }}
            var vr = model && model.visibleRange && model.visibleRange();
            if (vr) return {{from: vr.from, to: vr.to}};
            return null;
        }})()
        """)

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    async def get_ohlcv(self, count: int = 500, summary: bool = False) -> Any:
        js = f"""
        (function() {{
            var items = {_CHART_API}.chartWidget().model().mainSeries().bars()._items;
            var all = items.slice(-{count});
            var bars = all.map(function(it) {{
                var v = it.value;
                return {{timestamp: v[0], open: v[1], high: v[2], low: v[3], close: v[4], volume: v[5]}};
            }});
            if ({str(summary).lower()}) {{
                var highs = bars.map(function(b) {{ return b.high; }});
                var lows = bars.map(function(b) {{ return b.low; }});
                var closes = bars.map(function(b) {{ return b.close; }});
                return {{
                    count: bars.length,
                    high: Math.max.apply(null, highs),
                    low: Math.min.apply(null, lows),
                    open: bars[0].open,
                    close: closes[closes.length - 1],
                    avg_volume: Math.round(bars.reduce(function(s,b) {{ return s + b.volume; }}, 0) / bars.length),
                    range: (Math.max.apply(null, highs) - Math.min.apply(null, lows)).toFixed(2)
                }};
            }}
            return bars;
        }})()
        """
        return await self._eval(js)

    async def get_quote(self, symbol: str | None = None) -> dict[str, Any]:
        return await self._eval(f"""
        (function() {{
            var s = {_CHART_API}.symbol();
            return {{ symbol: s }};
        }})()
        """)

    async def get_study_values(self) -> dict[str, Any]:
        """Read current values from ALL visible indicator studies."""
        return await self._eval(f"""
        (function() {{
            var model = {_CHART_API}.chartWidget().model();
            var studies = {_CHART_API}.getAllStudies() || [];
            var result = {{}};
            studies.forEach(function(s) {{
                try {{
                    var ds = model.dataSourceForId(s.id);
                    if (!ds) {{ result[s.name] = {{error: 'no data source'}}; return; }}
                    var items = ds._data && ds._data._items;
                    if (!items || !items.length) {{ result[s.name] = {{error: 'no data'}}; return; }}
                    var values = [];
                    for (var i = 0; i < items.length; i++) {{
                        var v = items[i].value;
                        values.push({{timestamp: v[0], value: v[1]}});
                    }}
                    result[s.name] = {{title: ds.title ? ds.title() : s.name, values: values}};
                }} catch(e) {{
                    result[s.name] = {{error: e.message}};
                }}
            }});
            return result;
        }})()
        """)

    # ------------------------------------------------------------------
    # Indicators
    # ------------------------------------------------------------------

    async def add_indicator(
        self, study_id: str, inputs: dict[str, Any] | None = None
    ) -> str | None:
        """Add an indicator by study ID (e.g. 'RSI@tv-basicstudies').

        Returns the entity ID of the created study, or None on failure.
        Raises TooManyIndicatorsError if MAX_INDICATORS would be exceeded.
        """
        self._indicator_ids = set(await self._get_study_ids())
        if len(self._indicator_ids) >= MAX_INDICATORS:
            raise TooManyIndicatorsError(
                f"Chart already has {len(self._indicator_ids)} indicators "
                f"(max {MAX_INDICATORS}). Remove one first."
            )
        expr = f"""
        (function() {{
            return {_CHART_API}._createStudy({{type: "java", studyId: {_js_str(study_id)}}});
        }})()
        """
        eid = await self._eval(expr, await_promise=True)
        if eid:
            self._indicator_ids.add(eid)
        return eid

    async def remove_indicator(self, entity_id: str) -> None:
        await self._eval(f"({_CHART_API}.removeEntity({_js_str(entity_id)}))")
        self._indicator_ids.discard(entity_id)

    async def remove_all_indicators(self) -> None:
        """Remove all studies from the chart."""
        await self._eval(f"({_CHART_API}.removeAllStudies())")
        self._indicator_ids.clear()

    async def set_indicator_inputs(
        self, entity_id: str, inputs: dict[str, Any]
    ) -> None:
        """Change input values on an existing indicator."""
        overrides = json.dumps(inputs)
        await self._eval(f"""
        (function() {{
            var id = {_js_str(entity_id)};
            var inputs = {overrides};
            var chart = {_CHART_API};
            var model = chart.chartWidget().model();

            var study = null;

            // Strategy 1: public API
            try {{ study = chart.getStudyById(id); }} catch(e) {{}}

            // Strategy 2: dataSourceForId internals
            if (!study) {{
                try {{
                    var ds = model.dataSourceForId(id);
                    if (ds) {{
                        if (ds._study) {{
                            study = ds._study;
                        }} else if (ds._source) {{
                            study = ds._source;
                        }}
                    }}
                }} catch(e) {{}}
            }}

            // Strategy 3: search studies in panes
            if (!study) {{
                try {{
                    var panes = model.panes() || [];
                    for (var p = 0; p < panes.length; p++) {{
                        if (!panes[p].dataSources) continue;
                        var srcs = panes[p].dataSources() || [];
                        for (var s = 0; s < srcs.length; s++) {{
                            var src = srcs[s];
                            var srcId = src.id ? src.id() : src._id || '';
                            if (srcId === id) {{
                                study = src._study || src._source || src;
                                break;
                            }}
                        }}
                        if (study) break;
                    }}
                }} catch(e) {{}}
            }}

            if (!study) throw new Error('Study not found: ' + id);

            for (var k in inputs) {{
                if (study.setInputValue) {{
                    study.setInputValue(k, inputs[k]);
                }} else if (study._inputValues) {{
                    study._inputValues[k] = inputs[k];
                }}
            }}

            if (study.recalc) study.recalc();
            if (model.fullRecalc) model.fullRecalc();
            return true;
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
        js = f"""
        (function() {{
            var c = {_CHART_API};
            var lines = c.chartWidget().activeChart().getAllLines() || [];
            var result = [];
            lines.forEach(function(l) {{
                result.push({{id: l.id, price: l.price, text: l.text || ''}});
            }});
            return result;
        }})()
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
            var labels = {_CHART_API}
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

    async def _eval(self, expression: str, **kwargs: Any) -> Any:
        if not self._cdp:
            raise RuntimeError("Not connected. Call connect() first.")
        return await self._cdp.evaluate(expression, **kwargs)

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
