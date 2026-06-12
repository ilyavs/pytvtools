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
import os
from typing import Any

from pytvtools.cdp import CdpConnection, CdpError, find_tv_target, make_ws_url

logger = logging.getLogger(__name__)

MAX_INDICATORS = int(os.environ.get("TV_MAX_INDICATORS", "2"))


class TooManyIndicatorsError(RuntimeError):
    """Raised when adding an indicator would exceed MAX_INDICATORS."""


class SymbolNotFoundError(RuntimeError):
    """Raised when the requested symbol is not found or fails to load."""


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
        await self._close_dialogs()

    async def get_indicator_count(self) -> int:
        """Return the number of studies currently on the chart."""
        return len(await self._get_study_ids())

    async def list_templates(self, tab: str | None = None) -> list[dict[str, str]]:
        """List saved indicator templates.

        Parameters
        ----------
        tab : str or None
            Optional tab name to switch to before listing.
            One of ``"my templates"``, ``"technicals"``, ``"financials"``.
            Defaults to whichever tab is active when the dialog opens.
        """
        import asyncio

        await self._close_dialogs()

        await self._eval("""
        (function() {
            var btns = document.querySelectorAll(
                'button[aria-label="Indicator templates"]'
            );
            for (var i = 0; i < btns.length; i++) {
                var r = btns[i].getBoundingClientRect();
                if (r.x > 380) { btns[i].click(); return; }
            }
            throw new Error('Indicator templates button not found');
        })()
        """)
        await asyncio.sleep(0.5)

        await self._eval("""
        (function() {
            var items = document.querySelectorAll('[role="row"]');
            for (var i = 0; i < items.length; i++) {
                if (items[i].getAttribute('aria-label') === 'Open template\u2026') {
                    items[i].click();
                    return;
                }
            }
            throw new Error('Open template\u2026 not found');
        })()
        """)
        await asyncio.sleep(1)

        if tab:
            await self._eval(f"""
            (function() {{
                var tabs = document.querySelectorAll(
                    '[data-name="indicator-templates-dialog"] [role="tab"]'
                );
                for (var i = 0; i < tabs.length; i++) {{
                    var qa = tabs[i].getAttribute('data-qa-id') || '';
                    if (qa.toLowerCase() === {_js_str(tab.lower())}) {{
                        tabs[i].click();
                        return;
                    }}
                }}
            }})()
            """)
            await asyncio.sleep(0.5)

        templates = await self._eval("""
        (function() {
            var items = document.querySelectorAll(
                '[data-name="indicator-templates-dialog"] [data-role="list-item"]'
            );
            var out = [];
            items.forEach(function(item) {
                var title = item.getAttribute('data-title');
                if (!title) return;
                var desc = item.querySelector('.description-J4S_Zh_W');
                out.push({
                    name: title,
                    description: desc ? desc.textContent.trim() : '',
                });
            });
            return out;
        })()
        """)

        await self._close_dialogs()

        return templates or []

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

    async def set_symbol(self, symbol: str, timeout: float = 10, wait_data: bool = True) -> None:
        import asyncio
        prev = await self._eval(f"({_CHART_API}.symbol())")
        await self._eval(f"({_CHART_API}.setSymbol({_js_str(symbol)}))")
        for _ in range(15):
            await asyncio.sleep(0.3)
            current = await self._eval(f"({_CHART_API}.symbol())")
            if current != prev:
                break
        else:
            raise SymbolNotFoundError(
                f"Symbol '{symbol}' not found — chart did not change"
            )
        if wait_data:
            data_timeout = max(timeout - 4.5, 1)
            ready = await self.wait_for_chart_ready(timeout=data_timeout)
            if not ready:
                raise SymbolNotFoundError(
                    f"Symbol '{symbol}' loaded but data did not arrive"
                )

    async def set_timeframe(self, timeframe: str) -> None:
        await self._eval(f"({_CHART_API}.setResolution({_js_str(timeframe)}))")

    async def set_chart_type(self, chart_type: int | str) -> None:
        await self._eval(_chart_call("setChartType", chart_type))

    async def wait_for_chart_ready(
        self, expected_symbol: str | None = None, timeout: float = 10
    ) -> bool:
        """Poll DOM + chart API until the chart finishes loading.

        Checks for loading spinners, symbol-header match, and bar-count
        stability (via DOM *and* chart-model data).  ``expected_symbol``
        is matched case-insensitively after stripping any ``EXCHANGE:``
        prefix.  Returns ``True`` when ready, ``False`` on timeout.
        """
        import asyncio
        loop = asyncio.get_running_loop()
        start = loop.time()
        last_dom_bc = -1
        last_model_bc = -1
        stable = 0

        expected_ticker = (
            expected_symbol.split(":")[-1].upper() if expected_symbol and ":" in expected_symbol
            else (expected_symbol.upper() if expected_symbol else None)
        )

        while loop.time() - start < timeout:
            state = await self._eval(f"""
            (function() {{
                var spinner = document.querySelector('[class*="loader"]')
                    || document.querySelector('[data-name="loading"]');
                var isLoading = !!(spinner && spinner.offsetParent !== null);

                var domBarCount = -1;
                try {{ var b = document.querySelectorAll('[class*="bar"]'); domBarCount = b.length; }} catch(e) {{}}

                var el = document.querySelector('[data-name="legend-source-title"]')
                    || document.querySelector('[class*="title"] [class*="apply-common-tooltip"]');
                var sym = el ? el.textContent.trim() : '';

                var modelBars = -1;
                var validBars = -1;
                try {{
                    var items = {_CHART_API}.chartWidget().model()
                        .mainSeries().bars()._items;
                    modelBars = (items && items.length) || 0;
                    var count = 0;
                    for (var j = 0; j < (items || []).length; j++) {{
                        if (items[j] && items[j].value && items[j].value.length >= 6) count++;
                    }}
                    validBars = count;
                }} catch(e) {{}}

                return {{isLoading: isLoading, domBarCount: domBarCount, modelBars: modelBars, validBars: validBars, currentSymbol: sym}};
            }})()
            """)
            if state is None:
                await asyncio.sleep(0.2)
                continue
            if state.get("isLoading"):
                stable = 0
                await asyncio.sleep(0.2)
                continue
            if expected_ticker:
                cur = (state.get("currentSymbol") or "").upper()
                if expected_ticker not in cur:
                    stable = 0
                    await asyncio.sleep(0.2)
                    continue

            dom_bc = state.get("domBarCount", -1)
            model_bc = state.get("modelBars", -1)
            valid_bc = state.get("validBars", 0)
            bc_match = dom_bc == last_dom_bc and dom_bc > 0
            model_match = model_bc == last_model_bc and model_bc > 0
            if (bc_match or model_match) and valid_bc > 0:
                stable += 1
            else:
                stable = 0
            last_dom_bc = dom_bc
            last_model_bc = model_bc
            if stable >= 2:
                return True
            await asyncio.sleep(0.2)
        return False

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
            var bars = [];
            for (var i = 0; i < all.length; i++) {{
                var v = all[i].value;
                if (v && v.length >= 6) {{
                    bars.push({{timestamp: v[0], open: v[1], high: v[2], low: v[3], close: v[4], volume: v[5]}});
                }}
            }}
            if ({str(summary).lower()}) {{
                if (bars.length === 0) return null;
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

    async def get_quote(self) -> dict[str, Any]:
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

    @staticmethod
    def _decode_study_name(raw: str) -> str:
        """Decode TV's URL-encoded study name (``%1`` → space, etc.)."""
        import urllib.parse
        return urllib.parse.unquote(raw)

    async def search_indicators(self, query: str) -> list[dict[str, Any]]:
        """Search for indicators by keyword.

        Returns a list of dicts, each with keys:
          - ``id``       — data-id attribute (e.g. ``STD;RSI``)
          - ``name``     — display name (e.g. ``Relative Strength Index``)
          - ``study_id`` — usable with :meth:`add_indicator`
                           (e.g. ``RSI@tv-basicstudies`` for built-ins,
                           or raw ``PUB;85`` for community scripts).
        """
        import asyncio

        q = query.lower()

        await self._close_dialogs()

        # Ensure search dialog is open
        await self._eval("""
        (function() {
            var d = window.TradingViewApi._studyMarket._dialog;
            if (d && d._props) return;
            var btn = document.querySelector('[data-name=open-indicators-dialog]');
            if (btn) { btn.click(); }
        })()
        """)
        await asyncio.sleep(1.5)

        results = await self._eval(f"""
        (function() {{
            var d = window.TradingViewApi._studyMarket._dialog;
            if (!d) return [];

            var out = [];
            var seen = {{}};

            // Built-in studies (already loaded)
            var std = d._studies['Script$STD'] || {{}};
            var keys = Object.keys(std);
            for (var i = 0; i < keys.length; i++) {{
                var s = std[keys[i]];
                if (s.title && s.title.toLowerCase().indexOf({_js_str(q)}) >= 0) {{
                    if (seen[s.id]) continue;
                    seen[s.id] = true;
                    out.push({{id: s.id, name: s.title, publisher: ''}});
                }}
            }}

            return out;
        }})()
        """)
        results = results or []

        # Trigger server-side search for community scripts
        await self._eval(f"""
        (function() {{
            var d = window.TradingViewApi._studyMarket._dialog;
            if (d && d._handleSearch) d._handleSearch({_js_str(query)});
        }})()
        """)
        await asyncio.sleep(2)

        # Read community results from the dialog's search results
        pub_results = await self._eval("""
        (function() {
            var dlg = window.TradingViewApi._studyMarket._dialog;
            if (!dlg || !dlg._props) return [];
            var sr = dlg._props._value.searchResults;
            if (!sr) return [];
            var out = [];
            var seen = {};
            for (var t = 0; t < sr.length; t++) {
                var tab = sr[t];
                var content = tab.content || tab.filteredContent;
                if (!content) continue;
                var items = Array.isArray(content) ? content : [];
                for (var j = 0; j < items.length; j++) {
                    var item = items[j];
                    if (!item || !item.id) continue;
                    if (seen[item.id]) continue;
                    seen[item.id] = true;
                    var pub = item.public;
                    out.push({
                        id: item.id,
                        name: item.title || '',
                        publisher: pub ? (pub.authorName || '') : '',
                    });
                }
            }
            return out;
        })()
        """)
        pub_results = pub_results or []

        # Merge: built-ins first, then community (dedup by id)
        seen_ids = {r["id"] for r in results}
        for r in pub_results:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                results.append(r)

        # Enrich with study_id
        for r in results:
            raw_id = r["id"]
            if raw_id.startswith("STD;"):
                name = self._decode_study_name(raw_id[4:])
                r["study_id"] = f"{name}@tv-basicstudies"
            else:
                r["study_id"] = raw_id

        await self._close_dialogs()

        return results

    async def add_indicator(
        self, indicator: str, inputs: dict[str, Any] | None = None
    ) -> str | None:
        """Add an indicator by study ID **or** display name.

        Parameters
        ----------
        indicator : str
            Either a study ID (``RSI@tv-basicstudies``) or a display name
            (``Relative Strength Index``).  Display names are looked up
            via TV's own ``createStudy`` API.
        inputs : dict or None
            Optional input overrides applied after creation.

        Returns
        -------
        str or None
            Entity ID of the created study, or ``None`` if the indicator
            could not be found.

        Raises
        ------
        TooManyIndicatorsError
            If the chart already has ``MAX_INDICATORS`` indicators.
        """
        self._indicator_ids = set(await self._get_study_ids())
        if len(self._indicator_ids) >= MAX_INDICATORS:
            raise TooManyIndicatorsError(
                f"Chart already has {len(self._indicator_ids)} indicators "
                f"(max {MAX_INDICATORS}). Remove one first."
            )

        if "@" in indicator:
            # Built-in study ID — use _createStudy
            eid = await self._eval(f"""
            (function() {{
                return {_CHART_API}._createStudy({{type: "java", studyId: {_js_str(indicator)}}});
            }})()
            """, await_promise=True)
        elif indicator.startswith("PUB;"):
            # Community script — use _createStudy with pine type
            eid = await self._eval(f"""
            (function() {{
                return {_CHART_API}._createStudy({{type: "pine", pineId: {_js_str(indicator)}}});
            }})()
            """, await_promise=True)
        else:
            # Display name — use public createStudy
            try:
                eid = await self._eval(f"""
                (function() {{
                    return {_CHART_API}.createStudy({_js_str(indicator)});
                }})()
                """, await_promise=True)
            except CdpError:
                eid = None

        if eid:
            self._indicator_ids.add(eid)

        if inputs and eid:
            await self.set_indicator_inputs(eid, inputs)

        return eid

    async def remove_indicator(self, entity_id: str) -> None:
        await self._eval(f"({_CHART_API}.removeEntity({_js_str(entity_id)}))")
        self._indicator_ids.discard(entity_id)

    async def remove_all_indicators(self) -> None:
        """Remove all studies from the chart."""
        await self._eval(f"({_CHART_API}.removeAllStudies())", await_promise=True)
        self._indicator_ids.clear()

    async def apply_template(self, name: str) -> None:
        """Apply a saved indicator template by name.

        Opens the indicator templates menu, locates the template
        (recently used or full dialog), and activates it.
        """
        import asyncio

        await self._close_dialogs()

        # Open the indicator templates menu
        await self._eval("""
        (function() {
            var btns = document.querySelectorAll(
                'button[aria-label="Indicator templates"]'
            );
            for (var i = 0; i < btns.length; i++) {
                var r = btns[i].getBoundingClientRect();
                if (r.x > 380) { btns[i].click(); return; }
            }
            throw new Error('Indicator templates button not found');
        })()
        """)
        await asyncio.sleep(0.5)

        # Strategy 1: click the template directly from dropdown (recently used)
        found = await self._eval(f"""
        (function() {{
            var items = document.querySelectorAll('[role="row"]');
            for (var i = 0; i < items.length; i++) {{
                if (items[i].getAttribute('aria-label') === {_js_str(name)}) {{
                    items[i].click();
                    return true;
                }}
            }}
            return false;
        }})()
        """)

        if found:
            await asyncio.sleep(1)
            await self._close_dialogs()
            return

        # Strategy 2: open the full templates dialog
        await self._eval("""
        (function() {
            var items = document.querySelectorAll('[role="row"]');
            for (var i = 0; i < items.length; i++) {
                if (items[i].getAttribute('aria-label') === 'Open template\u2026') {
                    items[i].click();
                    return;
                }
            }
            throw new Error('Open template\u2026 not found');
        })()
        """)
        await asyncio.sleep(1)

        # Try the active tab first, then fall back to other tabs
        tabs_to_try = [None]  # None = current tab
        for tab_id in ("my templates", "technicals", "financials"):
            tabs_to_try.append(tab_id)

        found = False
        for tab_id in tabs_to_try:
            if tab_id is not None:
                await self._eval(f"""
                (function() {{
                    var tabs = document.querySelectorAll(
                        '[data-name="indicator-templates-dialog"] [role="tab"]'
                    );
                    for (var i = 0; i < tabs.length; i++) {{
                        var qa = tabs[i].getAttribute('data-qa-id') || '';
                        if (qa.toLowerCase() === {_js_str(tab_id)}) {{
                            tabs[i].click();
                            return;
                        }}
                    }}
                }})()
                """)
                await asyncio.sleep(0.5)

            clicked = await self._eval(f"""
            (function() {{
                var item = document.querySelector(
                    '[data-role="list-item"][data-title={_js_str(name)}]'
                );
                if (!item) return false;
                item.click();
                return true;
            }})()
            """)
            if clicked:
                found = True
                break

        if not found:
            raise RuntimeError(
                f"Template {_js_str(name)} not found in any tab"
            )

        await asyncio.sleep(1)
        await self._close_dialogs()

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
        await self._eval("""
        (function() {
            var btns = document.querySelectorAll('button');
            for (var i = 0; i < btns.length; i++) {
                var b = btns[i];
                var aria = (b.getAttribute('aria-label') || '').toLowerCase();
                var text = (b.textContent || '').trim().toLowerCase();
                if (aria.indexOf('compile') >= 0 || text.indexOf('add to chart') >= 0) {
                    b.click();
                    return;
                }
            }
            throw new Error('Compile button not found');
        })()
        """)
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

    async def capture_screenshot(self) -> str:
        """Returns base64-encoded PNG."""
        if not self._cdp:
            raise RuntimeError("Not connected")
        result = await self._cdp._send(
            "Page.captureScreenshot",
            {"format": "png", "fromSurface": True},
        )
        return result.get("data", "")

    async def get_indicator_data(self, entity_id: str) -> dict[str, Any] | None:
        """Get ALL historical plot data for an indicator by entity ID.

        Returns all plot values across all bars — unlike ``get_study_values``
        which only returns the last value per study.

        Parameters
        ----------
        entity_id : str
            The entity ID returned by :meth:`add_indicator`.

        Returns
        -------
        dict or None
            ``None`` if the data source is not found, otherwise::

                {
                    "id": "abc123",
                    "title": "BB (20, close, 2)",
                    "count": 400,
                    "plots": [
                        {
                            "name": "Basis",
                            "values": [
                                {"timestamp": 1700000000, "value": 150.5},
                                ...
                            ]
                        },
                        ...
                    ]
                }
        """
        return await self._eval(f"""
        (function() {{
            var model = {_CHART_API}.chartWidget().model();
            var ds = model.dataSourceForId({_js_str(entity_id)});
            if (!ds) return null;

            var mv = ds._metaInfo && ds._metaInfo._value;
            var plotNames = [];
            if (mv && mv.plots) {{
                for (var pk in mv.plots) {{
                    var sid = mv.plots[pk].id;
                    var title = (mv.styles && mv.styles[sid] && mv.styles[sid].title) || sid;
                    plotNames[parseInt(pk)] = title;
                }}
            }}

            var items = ds._data && ds._data._items;
            if (!items || !items.length) {{
                return {{
                    id: {_js_str(entity_id)},
                    title: ds.title ? ds.title() : '',
                    count: 0,
                    plots: [],
                }};
            }}

            var plotCount = ds._simplePlotsCount || 1;
            var plots = [];
            for (var p = 0; p < plotCount; p++) {{
                var pname = plotNames[p] || ('Plot ' + p);
                var values = [];
                for (var i = 0; i < items.length; i++) {{
                    var v = items[i].value;
                    values.push({{timestamp: v[0], value: v[p + 1]}});
                }}
                plots.push({{name: pname, values: values}});
            }}

            return {{
                id: {_js_str(entity_id)},
                title: ds.title ? ds.title() : '',
                count: items.length,
                plots: plots,
            }};
        }})()
        """)

    # ------------------------------------------------------------------
    # Batch
    # ------------------------------------------------------------------

    async def batch(
        self, symbols: list[str], timeframes: list[str], action: str = "ohlcv"
    ) -> dict[str, Any]:
        """Iterate symbols/timeframes and collect data (CDP-based).

        TradingView's per-user rate limit throttles after ~8 rapid
        ``setSymbol`` calls (~30s cooldown), so this method:

        1. Paces ``setSymbol`` calls ~1s apart to stay under the burst
           limit.
        2. Refreshes the chart session every 10 symbols.
        3. Retries failures one-at-a-time with progressive cooldown
           (5s → 15s → 30s), each on a fresh session.
        4. Stores partial data per-timeframe even if some timeframes
           fail — no data is discarded.

        Returns results for every symbol (partial data on failure).
        Always restores the original chart state.
        """
        import asyncio
        state = await self.get_state()
        original_symbol = state["symbol"]
        original_tf = state["timeframe"]

        results: dict[str, Any] = {}
        failed: list[str] = []

        RESET_EVERY = 10
        RETRY_WAITS = [5, 15, 30]

        async def _fetch(sym: str) -> tuple[dict[str, Any], bool]:
            """Set symbol, fetch data per timeframe, return (data, all_ok)."""
            try:
                await self.set_symbol(sym, wait_data=False)
            except SymbolNotFoundError:
                return {}, False
            data: dict[str, Any] = {}
            ok = True
            for tf in timeframes:
                await self.set_timeframe(tf)
                await asyncio.sleep(0.5)
                if action == "ohlcv":
                    val = await self.get_ohlcv(summary=True)
                    if val is None:
                        ok = False
                    data[tf] = val
                elif action == "studies":
                    data[tf] = await self.get_study_values()
            return data, ok

        async def _process_batch(syms: list[str]) -> None:
            nonlocal results, failed
            symbol_count = 0
            first = True
            for sym in syms:
                symbol_count += 1
                if symbol_count > RESET_EVERY:
                    logger.info("batch: resetting chart session to avoid rate limit")
                    await self._reset_chart_session()
                    await self.set_timeframe(original_tf)
                    symbol_count = 1
                    first = True

                if not first:
                    await asyncio.sleep(1)
                first = False

                data, ok = await _fetch(sym)
                results[sym] = data
                if not ok:
                    logger.warning("batch: %s partially failed — will retry", sym)
                    failed.append(sym)

        try:
            await _process_batch(symbols)

            for round_num, wait_sec in enumerate(RETRY_WAITS, 1):
                if not failed:
                    break
                syms = list(failed)
                failed = []
                logger.info(
                    "batch: retry round %d/%d — waiting %ds for cooldown, retrying %d symbols",
                    round_num, len(RETRY_WAITS), wait_sec, len(syms),
                )
                await asyncio.sleep(wait_sec)
                # One symbol at a time with its own reset — avoids
                # cascading rate limits across symbols in the same round.
                for sym in syms:
                    await self._reset_chart_session()
                    await self.set_timeframe(original_tf)
                    data, ok = await _fetch(sym)
                    results[sym] = data
                    if not ok:
                        failed.append(sym)

            if failed:
                for sym in failed:
                    # Keep any partial data already stored, only fill
                    # truly missing timeframes as None.
                    if sym not in results:
                        results[sym] = {tf: None for tf in timeframes}
                    else:
                        for tf in timeframes:
                            if tf not in results[sym]:
                                results[sym][tf] = None
                    logger.warning("batch: %s failed after all retries — skipping", sym)

        finally:
            logger.info("batch: restoring original state (%s)", original_symbol)
            await asyncio.sleep(1)
            try:
                await self.set_symbol(original_symbol)
            except SymbolNotFoundError:
                pass
            await self.set_timeframe(original_tf)

        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _reset_chart_session(self) -> None:
        """Navigate current tab to a fresh chart URL.

        Resets the per-session TradingView rate limit by creating a
        brand new WebSocket connection.  The CDP connection remains
        alive across navigation.  Waits until bar data is actually
        present in the model (not just chart().symbol() being non-null,
        which fires before the data WebSocket connects).
        """
        import asyncio
        chart_url = "https://www.tradingview.com/chart/"
        logger.info("_reset_chart_session: navigating to %s", chart_url)
        await self._eval(f"window.location.href = {_js_str(chart_url)}")
        nav_start = asyncio.get_running_loop().time()
        last_model_bc = -1
        stable = 0
        for i in range(60):
            await asyncio.sleep(0.5)
            try:
                state = await self._eval(f"""
                (function() {{
                    var mbc = -1;
                    var vbc = -1;
                    try {{
                        var items = {_CHART_API}.chartWidget().model()
                            .mainSeries().bars()._items;
                        mbc = (items && items.length) || 0;
                        var c = 0;
                        for (var j = 0; j < (items || []).length; j++) {{
                            if (items[j] && items[j].value && items[j].value.length >= 6) c++;
                        }}
                        vbc = c;
                    }} catch(e) {{}}
                    return {{modelBars: mbc, validBars: vbc}};
                }})()
                """)
                if not state:
                    continue
                mbc = state.get("modelBars", -1)
                vbc = state.get("validBars", 0)
                if mbc > 0 and vbc > 0 and mbc == last_model_bc:
                    stable += 1
                else:
                    stable = 0
                last_model_bc = mbc
                if stable >= 2:
                    elapsed = asyncio.get_running_loop().time() - nav_start
                    logger.info("_reset_chart_session: ready with %d bars after %.1fs", vbc, elapsed)
                    return
            except Exception as exc:
                if i < 5 or i % 5 == 0:
                    logger.debug("_reset_chart_session: attempt %d: %s", i, exc)
        logger.warning("_reset_chart_session: chart not ready within 30s")

    async def _close_dialogs(self) -> None:
        """Dismiss any open dialogs/menus via click-away and close buttons."""
        import asyncio
        await self._eval("document.body.click()")
        await asyncio.sleep(0.2)
        await self._eval("""
        (function() {
            var btns = document.querySelectorAll('[data-qa-id="close"], .dialog-close');
            for (var i = 0; i < btns.length; i++) { btns[i].click(); }
        })()
        """)
        await asyncio.sleep(0.2)

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
