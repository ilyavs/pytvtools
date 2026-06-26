"""
High-level TradingView client — the main interface for all TV operations.

Usage:
    async with TV(port=9222) as tv:
        await tv.set_symbol("BTCUSD")
        data = await tv.get_ohlcv(count=100)
        studies = await tv.get_study_values()
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
from typing import Any

from pytvtools.cdp import CdpConnection, CdpError, close_tab, create_new_tab, find_tv_target, make_ws_url

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
_REPLAY_API = "window.TradingViewApi._replayApi"



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
        self._target_id: str | None = None
        self._own_tab = False
        self._cdp: CdpConnection | None = None
        self._indicator_ids: set[str] = set()
        self._pine_source_cache: dict[str, str] = {}

    async def __aenter__(self) -> TV:
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.disconnect()

    async def connect(self) -> None:
        import asyncio
        if self._target:
            ws_url = make_ws_url(self._target)
            self._target_id = self._target.get("id")
            self._own_tab = False
        else:
            target = await find_tv_target(port=self.port)
            if target:
                self._own_tab = False
            else:
                logger.info("create_new_tab: creating blank page")
                target = await create_new_tab(port=self.port)
                self._own_tab = True
            self._target_id = target.get("id")
            ws_url = make_ws_url(target)
        self._cdp = CdpConnection(ws_url)
        await self._cdp.connect()
        if self._own_tab:
            # New tab — navigate to TradingView
            await self._eval("window.location.href = 'https://www.tradingview.com/chart/'")
            ready = await self.wait_for_chart_ready(timeout=30)
            if not ready:
                raise RuntimeError(
                    "TradingView chart did not load in the new tab"
                )
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
        try:
            ids = await self._eval(f"""
            (function() {{
                try {{
                    var studies = {_CHART_API}.getAllStudies() || [];
                    return studies.map(function(s) {{ return s.id; }});
                }} catch(e) {{ return []; }}
            }})()
            """)
            return ids or []
        except Exception:
            return []

    async def disconnect(self) -> None:
        if self._cdp:
            await self._cdp.close()
            self._cdp = None
        if self._own_tab and self._target_id:
            try:
                await close_tab(self._target_id, port=self.port)
            except Exception as exc:
                logger.warning("disconnect: failed to close tab %s: %s", self._target_id, exc)
            self._target_id = None
            self._own_tab = False

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
        if prev == symbol:
            return
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

    async def get_ohlcv(self, count: int | None = None, summary: bool = False) -> Any:
        slice_expr = "" if count is None else f".slice(-{count})"
        js = f"""
        (function() {{
            var items = {_CHART_API}.chartWidget().model().mainSeries().bars()._items;
            var all = items{slice_expr};
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
        """Read ALL historical values from every visible indicator study."""
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


    async def search_indicators(self, query: str) -> list[dict[str, Any]]:
        """Search for indicators by keyword.

        Returns a list of dicts, each with keys:
          - ``id``       — data-id attribute (e.g. ``STD;RSI``)
          - ``name``     — display name (e.g. ``Relative Strength Index``)
           - ``study_id`` — usable with :meth:`add_indicator`
                            (e.g. ``STD;RSI`` for built-ins,
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
        search_ok = await self._eval(f"""
        (function() {{
            var d = window.TradingViewApi._studyMarket._dialog;
            if (d && d._handleSearch) {{ d._handleSearch({_js_str(query)}); return true; }}
            return false;
        }})()
        """)
        if not search_ok:
            logger.warning("search_indicators: _handleSearch not found — server-side search may not work")
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

        # Enrich with study_id — STD studies use pine type internally,
        # so the raw "STD;Name" id is the correct pineId.
        for r in results:
            raw_id = r["id"]
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
            # Built-in study ID (java type) — use _createStudy
            eid = await self._eval(f"""
            (function() {{
                return {_CHART_API}._createStudy({{type: "java", studyId: {_js_str(indicator)}}});
            }})()
            """, await_promise=True)
        elif indicator.startswith("STD;"):
            # Built-in study (pine type) — e.g. STD;SMA, STD;RSI
            eid = await self._eval(f"""
            (function() {{
                return {_CHART_API}._createStudy({{type: "pine", pineId: {_js_str(indicator)}}});
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
            raise RuntimeError(f"Template '{name}' not found in any tab")

        await asyncio.sleep(1)
        await self._close_dialogs()

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def is_logged_in(self) -> bool:
        """Check if currently logged in to a TradingView account."""
        result = await self._eval("""
        (function() {
            try {
                // 1. Internal user object (most reliable)
                var u = window.TradingViewApi && window.TradingViewApi._user;
                if (u && u.id) return true;
            } catch(e) {}
            try {
                // 2. User menu button visible on chart
                var el = document.querySelector(
                    '[data-name="header-user-profile"], ' +
                    '[class*="userMenu"], ' +
                    '[class*="avatar"]' +
                    'button[aria-label*="user" i]'
                );
                if (el && el.offsetParent !== null) return true;
            } catch(e) {}
            try {
                // 3. "Publish" button = logged in, "Sign in" button = logged out
                var has_signin = false, has_publish = false;
                var btns = document.querySelectorAll('button');
                for (var i = 0; i < btns.length; i++) {
                    var t = btns[i].textContent.trim().toLowerCase();
                    if (t === 'sign in' || t === 'log in') has_signin = true;
                    if (t === 'publish') has_publish = true;
                }
                if (has_publish) return true;
                if (has_signin) return false;
            } catch(e) {}
            return false;
        })()
        """)
        return bool(result)

    async def login(
        self,
        username: str | None = None,
        password: str | None = None,
        timeout: float = 120,
        force: bool = False,
    ) -> dict[str, Any]:
        """Log in to a TradingView account.

        Two modes:

        * **Manual** (no arguments) — navigates to the sign-in page and waits
          for you to type your credentials in the browser.
        * **Programmatic** (with ``username`` + ``password``) — fills the form
          via CDP and submits.  Handles both one-step and two-step forms.

        Parameters
        ----------
        username : str or None
            Email or username.  Omit for manual mode.
        password : str or None
            Account password.  Omit for manual mode.
        timeout : float
            Maximum seconds to wait (default 120).
        force : bool
            If True, skip the ``is_logged_in()`` check and clear cookies first
            so the sign-in form always appears.  Useful for switching accounts.

        Returns
        -------
        dict
            Keys: ``success``, ``already_logged_in``, or ``error``.
        """
        import asyncio

        if not force and await self.is_logged_in():
            return {"success": True, "already_logged_in": True}

        if username and password:
            if force:
                # Clear cookies so the sign-in form doesn't redirect away
                try:
                    await self._cdp.send_command("Network.clearBrowserCookies")
                    await self._cdp.send_command("Storage.clearDataForOrigin", {
                        "origin": "https://www.tradingview.com",
                        "storageTypes": "cookies,local_storage,indexeddb,websql,cache_storage",
                    })
                except Exception:
                    pass
            try:
                return await self._login_programmatic(username, password, timeout)
            except Exception:
                return {"success": False, "error": "Login failed — check credentials or try manual mode"}

        # Manual mode — navigate and wait
        await self._close_dialogs()
        await self._eval("window.location.href = 'https://www.tradingview.com/accounts/signin/'")
        start = asyncio.get_running_loop().time()
        while asyncio.get_running_loop().time() - start < timeout:
            url = await self._eval("window.location.href")
            if url and "/chart/" in url:
                ready = await self.wait_for_chart_ready(
                    timeout=max(timeout - (asyncio.get_running_loop().time() - start), 5)
                )
                if ready:
                    return {"success": True}
            await asyncio.sleep(1)
        return {"success": False, "error": "Login timed out — did not detect redirect back to chart"}

    async def _login_programmatic(
        self, username: str, password: str, timeout: float
    ) -> dict[str, Any]:
        """Fill the sign-in form and submit. Handles one-step and two-step flows."""
        import asyncio

        await self._eval("window.location.href = 'https://www.tradingview.com/accounts/signin/'")

        # Wait for the email input (with one retry to click "Email" button)
        found_email = False
        for _ in range(int(timeout / 0.5)):
            has_email = await self._eval("""
            (function() {
                var el = document.querySelector(
                    'input[name="email"], input[type="email"], ' +
                    'input[name="username"], input[name="id_username"], ' +
                    'input[autocomplete="username"]'
                );
                if (el && el.offsetParent !== null) return 'visible';
                if (el) return 'exists';
                return false;
            })()
            """)
            if has_email:
                found_email = True
                break
            # Check if we need to click the "Email" button first
            if _ == 10:
                await self._eval("""
                (function() {
                    var btns = document.querySelectorAll('button');
                    for (var b of btns) {
                        var t = b.textContent.trim();
                        if ((t === 'Email' || t === 'EmailEmail') && b.offsetParent !== null) {
                            b.click(); return true;
                        }
                    }
                    return false;
                })()
                """)
            await asyncio.sleep(0.5)

        if not found_email:
            return {"success": False, "error": "Sign-in form did not load within timeout"}

        # Fill email
        await self._eval(f"""
        (function() {{
            var input = document.querySelector(
                'input[name="email"], input[type="email"], ' +
                'input[name="username"], input[name="id_username"], ' +
                'input[autocomplete="username"]'
            );
            if (!input) return false;
            var setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            ).set;
            setter.call(input, {_js_str(username)});
            input.dispatchEvent(new Event('input', {{bubbles: true}}));
            input.dispatchEvent(new Event('change', {{bubbles: true}}));
            return true;
        }})()
        """)
        await asyncio.sleep(0.3)

        # Check if password is already visible (one-step form)
        has_pw = await self._eval("""
        (function() {
            var pw = document.querySelector(
                'input[type="password"], input[name="password"], ' +
                'input[name="id_password"], input[autocomplete="current-password"]'
            );
            return !!(pw && pw.offsetParent !== null);
        })()
        """)

        if not has_pw:
            # Two-step — click Continue / Next (NOT "Sign in" — that submits early)
            await self._eval("""
            (function() {
                var btns = document.querySelectorAll('button');
                for (var i = 0; i < btns.length; i++) {
                    var t = btns[i].textContent.trim().toLowerCase();
                    if (t === 'continue' || t === 'next') {
                        btns[i].click(); return true;
                    }
                }
                return false;
            })()
            """)
            await asyncio.sleep(1.5)

        # Fill password
        await self._eval(f"""
        (function() {{
            var input = document.querySelector(
                'input[type="password"], input[name="password"], ' +
                'input[name="id_password"], input[autocomplete="current-password"]'
            );
            if (!input) return false;
            var setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            ).set;
            setter.call(input, {_js_str(password)});
            input.dispatchEvent(new Event('input', {{bubbles: true}}));
            input.dispatchEvent(new Event('change', {{bubbles: true}}));
            return true;
        }})()
        """)
        await asyncio.sleep(0.3)

        # Click Sign In
        await self._eval("""
        (function() {
            var btns = document.querySelectorAll('button');
            for (var i = 0; i < btns.length; i++) {
                var t = btns[i].textContent.trim().toLowerCase();
                if (t === 'sign in' || t === 'log in') {
                    btns[i].click(); return true;
                }
            }
            return false;
        })()
        """)

        # Wait for redirect away from sign-in page
        start = asyncio.get_running_loop().time()
        while asyncio.get_running_loop().time() - start < timeout:
            url = await self._eval("window.location.href") or ""

            # Check for captcha / 2fa blocks
            body = (await self._eval("document.body.innerText.substring(0,500)") or "").lower()
            if "captcha" in body:
                return {"success": False, "error": "CAPTCHA challenge — cannot log in programmatically"}
            if any(t in body for t in ("two-factor", "2fa", "authenticator", "verification code")):
                return {"success": False, "error": "Two-factor authentication required — cannot log in programmatically"}

            # Direct to chart — success
            if "/chart/" in url and "/signin" not in url:
                ready = await self.wait_for_chart_ready(
                    timeout=max(timeout - (asyncio.get_running_loop().time() - start), 5)
                )
                if ready:
                    return {"success": True}
            # Non-signin URL (homepage, etc.) — navigate to chart
            if url and "/signin" not in url and "/chart/" not in url:
                await self._eval("window.location.href = 'https://www.tradingview.com/chart/'")
                ready = await self.wait_for_chart_ready(
                    timeout=max(timeout - (asyncio.get_running_loop().time() - start), 5)
                )
                if ready:
                    return {"success": True}
            await asyncio.sleep(1)
        return {"success": False, "error": "Login timed out — did not redirect to chart"}

    async def logout(self, timeout: float = 10) -> dict[str, Any]:
        """Log out of the current TradingView account.

        Attempts UI logout first (click avatar -> sign out), then falls
        back to clearing browser cookies via CDP if the UI path fails.

        Parameters
        ----------
        timeout : float
            Maximum seconds to wait for logout to complete.

        Returns
        -------
        dict
            Keys: ``success``, ``already_logged_out``, or ``error``.
        """
        import asyncio

        if not await self.is_logged_in():
            return {"success": True, "already_logged_out": True}

        # --- Method 1: UI click path ---
        avatar_clicked = await self._eval("""
        (function() {
            var sel = [
                '[data-name="header-user-profile"]',
                'button[class*="avatar"]',
                'button[class*="userMenu"]',
                '[class*="userWidget"]',
                'button[aria-label*="user" i]',
                'button[aria-label*="profile" i]',
                'button[aria-label*="account" i]',
            ];
            for (var s of sel) {
                var el = document.querySelector(s);
                if (el && el.offsetParent !== null) { el.click(); return true; }
            }
            // Try finding any img with avatar/user class and clicking its parent
            var imgs = document.querySelectorAll('img[class*="avatar"], img[class*="user"]');
            for (var i = 0; i < imgs.length; i++) {
                var btn = imgs[i].closest('button');
                if (btn) { btn.click(); return true; }
            }
            return false;
        })()
        """)
        if avatar_clicked:
            await asyncio.sleep(1)
            signout_clicked = await self._eval("""
            (function() {
                // Look in any visible popup/menu/dropdown
                var containers = document.querySelectorAll(
                    '[role="menu"], [role="listbox"], [class*="dropdown"], ' +
                    '[class*="popup"], [class*="menu"], ' +
                    'div[class*="overlay"]'
                );
                for (var c = 0; c < containers.length; c++) {
                    if (containers[c].offsetParent === null) continue;
                    var items = containers[c].querySelectorAll('li, a, div, button, span');
                    for (var i = 0; i < items.length; i++) {
                        if (items[i].textContent.trim().toLowerCase() === 'sign out') {
                            items[i].click();
                            return true;
                        }
                    }
                }
                // Also search the full document
                var all = document.querySelectorAll('li, a, div, button, span');
                for (var i = 0; i < all.length; i++) {
                    if (all[i].offsetParent !== null &&
                        all[i].textContent.trim().toLowerCase() === 'sign out') {
                        all[i].click();
                        return true;
                    }
                }
                return false;
            })()
            """)
            if signout_clicked:
                start = asyncio.get_running_loop().time()
                while asyncio.get_running_loop().time() - start < timeout:
                    url = await self._eval("window.location.href")
                    if url and "/chart/" not in url:
                        return {"success": True}
                    await asyncio.sleep(1)
                return {"success": True, "note": "Sign Out clicked, but URL did not change"}

        # --- Method 2: CDP cookie clearing ---
        try:
            await self._cdp.send_command("Network.clearBrowserCookies")
            await self._cdp.send_command("Storage.clearDataForOrigin", {
                "origin": "https://www.tradingview.com",
                "storageTypes": "cookies,local_storage,indexeddb,websql,cache_storage",
            })
            await self._eval("localStorage.clear(); sessionStorage.clear()")
            # Navigate to chart to verify
            await self._eval("window.location.href = 'https://www.tradingview.com/chart/'")
            await asyncio.sleep(3)
            logged_in = await self.is_logged_in()
            if not logged_in:
                return {"success": True, "method": "cdp_clear"}
            return {"success": False, "error": "CDP cookie clearing did not log out"}
        except Exception as e:
            return {"success": False, "error": f"Logout failed: {e}"}

    async def set_indicator_inputs(
        self, entity_id: str, inputs: dict[str, Any]
    ) -> None:
        """Change input values on an existing indicator.

        Retries up to 10 times with 500ms delay for cases where the study
        was just created and isn't yet registered in the chart model.
        """
        import asyncio

        overrides = json.dumps(inputs)
        for attempt in range(10):
            ok = await self._eval(f"""
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

                if (!study) return false;

                if (study.setInputValues) {{
                    var arr = [];
                    for (var k in inputs) {{
                        arr.push({{id: k, value: inputs[k]}});
                    }}
                    study.setInputValues(arr);
                }} else {{
                    for (var k in inputs) {{
                        if (study.setInputValue) {{
                            study.setInputValue(k, inputs[k]);
                        }} else if (study._inputValues) {{
                            study._inputValues[k] = inputs[k];
                        }}
                    }}
                    if (study.recalc) study.recalc();
                }}

                if (model.fullRecalc) model.fullRecalc();
                return true;
            }})()
            """)
            if ok:
                return
            await asyncio.sleep(0.5)

        logger.warning(
            "Could not set inputs on study %s (not found after 10 retries)",
            entity_id,
        )

    # ------------------------------------------------------------------
    # Pine Script
    # ------------------------------------------------------------------

    _FIND_MONACO: str = """
(function() {
    var container = document.querySelector('.monaco-editor.pine-editor-monaco');
    if (!container) return null;
    var el = container;
    var fiberKey;
    for (var i = 0; i < 20; i++) {
        if (!el) break;
        fiberKey = Object.keys(el).find(function(k) { return k.startsWith('__reactFiber$'); });
        if (fiberKey) break;
        el = el.parentElement;
    }
    if (!fiberKey) return null;
    var current = el[fiberKey];
    for (var d = 0; d < 15; d++) {
        if (!current) break;
        if (current.memoizedProps && current.memoizedProps.value && current.memoizedProps.value.monacoEnv) {
            var env = current.memoizedProps.value.monacoEnv;
            if (env.editor && typeof env.editor.getEditors === 'function') {
                var editors = env.editor.getEditors();
                if (editors.length > 0) return { editor: editors[0], env: env };
            }
        }
        current = current.return;
    }
    return null;
})()
"""

    async def pine_set_source(self, source: str) -> None:
        """Set Pine Script source in the editor via Monaco API directly.

        Walks the React fiber tree to find the Monaco editor instance
        and calls ``editor.setValue()`` — the standard Monaco API.
        """
        escaped = source.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
        result = await self._eval(f"""
        (function() {{
            var m = {self._FIND_MONACO};
            if (!m) throw new Error('Monaco editor not found — Pine Editor may not be open');
            m.editor.setValue(`{escaped}`);
            return true;
        }})()
        """)
        if not result:
            raise RuntimeError("Failed to set Pine Script source")

    async def pine_compile(self) -> dict[str, Any]:
        """Click the compile button and return errors from Monaco markers."""
        clicked = await self._eval("""
        (function() {
            var btns = document.querySelectorAll('button');
            var fallback = null;
            for (var i = 0; i < btns.length; i++) {
                var text = btns[i].textContent.trim();
                if (/save and add to chart/i.test(text)) {
                    btns[i].click();
                    return 'save_and_add';
                }
                if (!fallback && /^(Add to chart|Update on chart)/i.test(text)) {
                    fallback = btns[i];
                }
            }
            if (fallback) { fallback.click(); return fallback.textContent.trim(); }
            return null;
        })()
        """)
        import asyncio
        if not clicked:
            await self._cdp.send_command("Input.dispatchKeyEvent", {
                "type": "rawKeyDown", "modifiers": 2, "windowsVirtualKeyCode": 13,
            })
            await self._cdp.send_command("Input.dispatchKeyEvent", {
                "type": "keyUp", "modifiers": 2, "windowsVirtualKeyCode": 13,
            })
        await asyncio.sleep(2)
        errors = await self._eval(f"""
        (function() {{
            var m = {self._FIND_MONACO};
            if (!m) return [];
            var model = m.editor.getModel();
            if (!model) return [];
            var markers = m.env.editor.getModelMarkers({{ resource: model.uri }});
            return markers.map(function(mk) {{
                return {{
                    line: mk.startLineNumber,
                    column: mk.startColumn,
                    message: mk.message,
                    severity: mk.severity,
                }};
            }});
        }})()
        """)
        return {"errors": errors}

    async def pine_get_errors(self) -> list[dict]:
        """Read Pine Script compilation errors from Monaco markers."""
        return await self._eval(f"""
        (function() {{
            var m = {self._FIND_MONACO};
            if (!m) return [];
            var model = m.editor.getModel();
            if (!model) return [];
            var markers = m.env.editor.getModelMarkers({{ resource: model.uri }});
            return markers.map(function(mk) {{
                return {{
                    line: mk.startLineNumber,
                    column: mk.startColumn,
                    message: mk.message,
                    severity: mk.severity,
                }};
            }});
        }})()
        """)

    async def pine_get_editor_source(self) -> str | None:
        """Read the current Pine Script source from the editor."""
        return await self._eval(f"""
        (function() {{
            var m = {self._FIND_MONACO};
            if (!m) return null;
            return m.editor.getValue();
        }})()
        """)

    async def pine_close_editor(self) -> bool:
        """Close the Pine Script editor panel.

        Clicks the ``aria-label="Close"`` button on the editor container.
        Returns ``True`` if a close button was found and clicked.
        """
        return bool(await self._eval("""
        (function() {
            var btns = document.querySelectorAll('button');
            for (var i = 0; i < btns.length; i++) {
                var aria = (btns[i].getAttribute('aria-label') || '').trim().toLowerCase();
                if (aria === 'close') {
                    btns[i].click();
                    return true;
                }
            }
            return false;
        })()
        """))

    async def _get_script_page_url(self, study_id: str) -> str | None:
        """Resolve ``PUB;id`` to its TradingView script page URL.

        Opens the indicators dialog, triggers a server-side search, reads
        the script hash (from ``item.public.imageUrl``) and display name,
        then constructs ``https://www.tradingview.com/script/{hash}-{slug}/``.

        Returns ``None`` for built-in studies (``STD;``), or when the
        script is not found or its source is not publicly visible.
        """
        if not study_id.startswith("PUB;"):
            return None

        import asyncio

        await self._close_dialogs()

        # Open the indicators dialog so search is available
        await self._eval("""
        (function() {
            var btn = document.querySelector('[data-name=open-indicators-dialog]');
            if (btn) { btn.click(); return true; }
            return false;
        })()
        """)
        await asyncio.sleep(1.5)

        # Trigger server-side search for the exact study
        await self._eval(f"""
        (function() {{
            var d = TradingViewApi._studyMarket._dialog;
            if (d && d._handleSearch) {{
                d._handleSearch({_js_str(study_id)});
                return true;
            }}
            return false;
        }})()
        """)
        await asyncio.sleep(3)

        # Read hash + name from the search results
        result = await self._eval(f"""
        (function() {{
            var dlg = TradingViewApi._studyMarket._dialog;
            if (!dlg || !dlg._props) return null;
            var sr = dlg._props._value.searchResults;
            if (!sr) return null;

            for (var t = 0; t < sr.length; t++) {{
                var tab = sr[t];
                var content = tab.content || tab.filteredContent;
                if (!content) continue;
                var items = Array.isArray(content) ? content : [];
                for (var j = 0; j < items.length; j++) {{
                    var item = items[j];
                    if (item && item.id === {_js_str(study_id)}) {{
                        var pub = (typeof item.public === 'string')
                            ? JSON.parse(item.public)
                            : (item.public || {{}});
                        var hash = pub.imageUrl || '';
                        var name = item.shortDescription || item.title || '';
                        var visible = String(item.isSourceVisible) === 'true';
                        return JSON.stringify({{hash: hash, name: name, visible: visible}});
                    }}
                }}
            }}
            return null;
        }})()
        """)

        await self._close_dialogs()

        if not result:
            return None

        data = json.loads(result)
        if not data.get("hash") or not data.get("visible"):
            return None

        # Build URL slug from the display name
        name = data["name"]
        slug = name.replace(" ", "-")
        slug = slug.replace("--", "-")
        slug = "".join(c for c in slug if c.isalnum() or c == "-")
        slug = slug.strip("-").lower()

        return f"https://www.tradingview.com/script/{data['hash']}-{slug}/"

    async def _extract_source_from_page(self, url: str) -> str | None:
        """Navigate to a script page, click 'Source code', extract Pine source.

        Restores the original chart URL after extraction (waits
        up to 15 s for the chart to be ready again).
        """
        import asyncio

        current_url = await self._eval("window.location.href")
        if current_url == "about:blank":
            current_url = None

        try:
            await self._eval(f"window.location.href = {_js_str(url)}")
            await asyncio.sleep(8)

            await self._eval("""
            (function() {
                var buttons = document.querySelectorAll('button');
                for (var i = 0; i < buttons.length; i++) {
                    if (buttons[i].innerText === 'Source code') {
                        buttons[i].click();
                        return true;
                    }
                }
                return false;
            })()
            """)
            await asyncio.sleep(3)

            b64 = await self._eval("""
            (function() {
                var pres = document.querySelectorAll('pre');
                if (pres.length && pres[0].innerText.length > 50) {
                    return btoa(unescape(encodeURIComponent(pres[0].innerText)));
                }
                var codes = document.querySelectorAll('code');
                for (var i = 0; i < codes.length; i++) {
                    var t = codes[i].innerText || '';
                    if (t.length > 50 && t.indexOf('//@version') >= 0) {
                        return btoa(unescape(encodeURIComponent(t)));
                    }
                }
                return '';
            })()
            """)

            if not b64:
                return None
            return base64.b64decode(b64).decode("utf-8")
        finally:
            if current_url:
                await self._eval(f"window.location.href = {_js_str(current_url)}")
                await asyncio.sleep(5)

    async def get_pine_source(
        self, study_id: str, entity_id: str | None = None
    ) -> str | None:
        """Fetch the Pine Script source code of any public indicator.

        Works for community scripts (``PUB;id``).  Built-in studies
        (``STD;Name``) typically return ``None`` since their source is
        not publicly available.

        Results are cached per session in ``_pine_source_cache`` keyed
        by ``study_id``.

        Parameters
        ----------
        study_id : str
            Study ID in ``PUB;id`` format (e.g. ``"PUB;85"``) or
            ``STD;Name`` format.
        entity_id : str | None
            If the indicator is already on the chart, pass its entity ID
            to read the source from the chart model directly (avoids the
            HTTP request).

        Returns
        -------
        str or None
            The Pine Script source code, or ``None`` if not available.
        """
        if study_id in self._pine_source_cache:
            return self._pine_source_cache[study_id]

        # Strategy 1: read from chart model if already added
        if entity_id:
            source = await self._eval(f"""
            (function() {{
                var ds = {_CHART_API}.chartWidget().model()
                    .dataSourceForId({_js_str(entity_id)});
                if (ds && ds._study && ds._study._script) {{
                    return ds._study._script.source || null;
                }}
                return null;
            }})()
            """)
            if source:
                self._pine_source_cache[study_id] = source
                return source

        # Strategy 2: fetch from TradingView's pine script API
        if study_id.startswith("PUB;"):
            pub_id = study_id.split(";", 1)[1]
            source = await self._eval(f"""
            (async function() {{
                try {{
                    var resp = await fetch(
                        'https://www.tradingview.com/pine_script/public/'
                        + {_js_str(pub_id)}
                    );
                    var data = await resp.json();
                    return data.source || null;
                }} catch(e) {{
                    return null;
                }}
            }})()
            """, await_promise=True)
            if source:
                self._pine_source_cache[study_id] = source
                return source

            # Strategy 3: navigate to script page and extract from "Source code" tab
            url = await self._get_script_page_url(study_id)
            if url:
                source = await self._extract_source_from_page(url)
                if source:
                    self._pine_source_cache[study_id] = source
                    return source

        self._pine_source_cache[study_id] = None
        return None

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
        result = await self._cdp.send_command(
            "Page.captureScreenshot",
            {"format": "png", "fromSurface": True},
        )
        return result.get("data", "")

    async def get_indicator_data(self, entity_id: str) -> dict[str, Any] | None:
        """Get ALL historical plot values for an indicator by entity ID.

        Returns multi-plot data organized by plot name with per-bar
        ``{timestamp, value}`` arrays — unlike ``get_study_values``
        which filters data through the public API and only returns the
        last value per study.  This method reads from the internal data
        source directly.

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
                    values.push({{timestamp: v[0], value: (v.length > p + 1 ? v[p + 1] : null)}});
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
        self, symbols: list[str], timeframes: list[str], action: str = "ohlcv", max_bars: int | None = None
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

        Parameters
        ----------
        action : str
            ``"ohlcv"`` — summary stats only.
            ``"studies"`` — indicator values only.
            ``"all"`` — both in one pass, returns nested dict per
            timeframe: ``{"ohlcv": ..., "studies": ...}``.
        max_bars : int or None
            Maximum bars to fetch per timeframe (passed to
            ``get_ohlcv(count=max_bars)``).  ``None`` (default) returns
            all available bars.

        Returns results for every symbol (partial data on failure).
        Always restores the original chart state.
        """
        import asyncio
        if action not in ("ohlcv", "studies", "all"):
            raise ValueError(f"batch: unknown action {action!r} (expected 'ohlcv', 'studies' or 'all')")

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
                    val = await self.get_ohlcv(count=max_bars, summary=True)
                    if val is None:
                        ok = False
                    data[tf] = val
                elif action == "studies":
                    val = await self.get_study_values()
                    if not val:
                        ok = False
                    data[tf] = val
                elif action == "all":
                    ohlcv_val = await self.get_ohlcv(count=max_bars, summary=True)
                    studies_val = await self.get_study_values()
                    if ohlcv_val is None and not studies_val:
                        ok = False
                    data[tf] = {"ohlcv": ohlcv_val, "studies": studies_val}
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
                for sym in syms:
                    await self._reset_chart_session()
                    await self.set_timeframe(original_tf)
                    data, ok = await _fetch(sym)
                    results[sym] = data
                    if not ok:
                        failed.append(sym)

            if failed:
                for sym in failed:
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
            try:
                await self.set_timeframe(original_tf)
            except Exception:
                pass

        return results

    # ------------------------------------------------------------------
    # Bar replay
    # ------------------------------------------------------------------

    async def replay_start(self, date: str | None = None) -> dict[str, Any]:
        """Enter bar-replay mode, optionally at a specific date.

        Parameters
        ----------
        date : str | None
            ISO date (``"2024-01-15"``) or ``None`` for the first
            available date.

        Returns
        -------
        dict
            Keys: ``success``, ``replay_started``, ``date``,
            ``current_date``.
        """
        import asyncio
        rp = _REPLAY_API
        available = await self._eval(f"{rp}.isReplayAvailable()")
        if not available:
            return {"success": False, "error": "Replay not available for this symbol/timeframe"}

        await self._eval(f"{rp}.showReplayToolbar()")
        await asyncio.sleep(0.5)

        if date:
            await self._eval(f"{rp}.selectDate(new Date({_js_str(date)}))")
        else:
            await self._eval(f"{rp}.selectFirstAvailableDate()")
        await asyncio.sleep(1)

        started = await self._eval(f"{rp}.isReplayStarted()")
        current_date = await self._eval(f"{rp}.currentDate()")
        return {
            "success": True,
            "replay_started": bool(started),
            "date": date or "(first available)",
            "current_date": current_date,
        }

    async def replay_stop(self) -> dict[str, Any]:
        """Stop replay mode and return to realtime."""
        rp = _REPLAY_API
        started = await self._eval(f"{rp}.isReplayStarted()")
        if not started:
            await self._eval(f"{rp}.hideReplayToolbar()")
            return {"success": True, "action": "already_stopped"}
        await self._eval(f"{rp}.stopReplay()")
        await self._eval(f"{rp}.hideReplayToolbar()")
        return {"success": True, "action": "replay_stopped"}

    async def replay_status(self) -> dict[str, Any]:
        """Get current replay mode state."""
        rp = _REPLAY_API
        result = await self._eval(f"""
        (function() {{
            var r = {rp};
            return {{
                is_replay_available: r.isReplayAvailable(),
                is_replay_started: r.isReplayStarted(),
                is_autoplay_started: r.isAutoplayStarted(),
                replay_mode: r.replayMode(),
                current_date: r.currentDate(),
                autoplay_delay: r.autoplayDelay(),
            }};
        }})()
        """)
        return result

    async def replay_step(self) -> dict[str, Any]:
        """Advance one bar in replay mode."""
        rp = _REPLAY_API
        started = await self._eval(f"{rp}.isReplayStarted()")
        if not started:
            return {"success": False, "error": "Replay not started. Call replay_start() first."}
        await self._eval(f"{rp}.doStep()")
        current_date = await self._eval(f"{rp}.currentDate()")
        return {"success": True, "action": "step", "current_date": current_date}

    async def replay_autoplay(self, speed: int = 0) -> dict[str, Any]:
        """Toggle autoplay in replay mode, optionally set speed.

        Parameters
        ----------
        speed : int
            Autoplay delay in ms (lower = faster). ``0`` to just toggle.
        """
        rp = _REPLAY_API
        started = await self._eval(f"{rp}.isReplayStarted()")
        if not started:
            return {"success": False, "error": "Replay not started. Call replay_start() first."}
        speed = int(speed)
        if speed > 0:
            await self._eval(f"{rp}.changeAutoplayDelay({speed})")
        await self._eval(f"{rp}.toggleAutoplay()")
        is_autoplay = await self._eval(f"{rp}.isAutoplayStarted()")
        delay = await self._eval(f"{rp}.autoplayDelay()")
        return {"success": True, "autoplay_active": bool(is_autoplay), "delay_ms": delay}

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
        # Also dismiss overlay ads
        await self._eval("""
        (function() {
            var btns = document.querySelectorAll('button');
            for (var i = 0; i < btns.length; i++) {
                var text = (btns[i].textContent || '').trim().toLowerCase();
                if (text === 'close ad') { btns[i].click(); }
            }
        })()
        """)
        await asyncio.sleep(0.2)

    async def dismiss_ad(self) -> bool:
        """Dismiss overlay ads on the chart. Returns ``True`` if an ad was closed."""
        import asyncio
        found = bool(await self._eval("""
        (function() {
            var btns = document.querySelectorAll('button, [role="button"]');
            for (var i = 0; i < btns.length; i++) {
                var b = btns[i];
                var text = (b.textContent || '').trim().toLowerCase();
                var aria = (b.getAttribute('aria-label') || '').toLowerCase();
                if (text === 'close ad' || aria === 'close ad') {
                    b.click();
                    return true;
                }
            }
            return false;
        })()
        """))
        if found:
            await asyncio.sleep(0.3)
        return found

    async def _eval(self, expression: str, **kwargs: Any) -> Any:
        if not self._cdp:
            raise RuntimeError("Not connected. Call connect() first.")
        result = await self._cdp.evaluate(expression, **kwargs)
        try:
            await self._cdp.evaluate("""
            (function() {
                var btns = document.querySelectorAll('button, [role="button"]');
                for (var i = 0; i < btns.length; i++) {
                    var b = btns[i];
                    var text = (b.textContent || '').trim().toLowerCase();
                    var aria = (b.getAttribute('aria-label') || '').toLowerCase();
                    if (text === 'close ad' || aria === 'close ad') {
                        b.click();
                        break;
                    }
                }
            })()
            """)
        except Exception:
            pass
        return result

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
