"""Self-contained HTML chart generator using Lightweight Charts.

Usage::

    from pytvtools_core.chart import Chart

    chart = Chart(title="BTCUSD - Daily")
    chart.set_candles(bars)
    chart.add_line(sma_vals, name="SMA 50", color="#4E5185")
    chart.render()  # -> HTML string
    chart.save("chart.html")  # -> file

Data-source agnostic — accepts any list of dicts with
``timestamp`` / ``time`` + OHLCV keys.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any


def _format_time(ts: float, timeframe: str | None = None) -> str | int:
    """Convert unix timestamp (seconds) to Lightweight Charts time format.

    Daily/weekly/monthly data uses ISO date strings; intraday uses unix
    seconds (integer).  Auto-detects daily when the timestamp falls at
    midnight UTC.
    """
    if timeframe:
        tf = timeframe.upper().strip()
        if tf in ("D", "W", "M") or tf[-1] in ("D", "W", "M"):
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
        return dt.strftime("%Y-%m-%d")
    return int(ts)


def _extract_bars(
    bars: list[dict[str, Any]],
    timeframe: str | None = None,
) -> tuple[list[str | int], list[dict[str, Any]], list[float]]:
    """Convert raw OHLCV bars into Lightweight Charts candle format.

    Returns ``(times, candles, volumes)``.
    """
    times: list[str | int] = []
    candles: list[dict[str, Any]] = []
    volumes: list[float] = []
    for b in bars:
        raw = b.get("time", b.get("timestamp", 0))
        if isinstance(raw, float):
            t = _format_time(raw, timeframe)
        elif isinstance(raw, int) and raw > 1e10:
            t = _format_time(raw, timeframe)
        else:
            t = raw
        times.append(t)
        candles.append({
            "time": t,
            "open": float(b["open"]),
            "high": float(b["high"]),
            "low": float(b["low"]),
            "close": float(b["close"]),
        })
        volumes.append(float(b.get("volume", 0)))
    return times, candles, volumes


def _escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── chart / series style presets ──────────────────────────────────────

_CHART_LAYOUT: dict[str, Any] = {
    "layout": {
        "textColor": "#E8ECF0",
        "background": {"type": "solid", "color": "#11171C"},
    },
    "grid": {
        "vertLines": {"color": "#2A3440"},
        "horzLines": {"color": "#2A3440"},
    },
    "crosshair": {"mode": 0},
    "rightPriceScale": {"borderColor": "#2A3440"},
    "timeScale": {
        "timeVisible": True,
        "secondsVisible": False,
        "borderColor": "#2A3440",
    },
}

_CANDLE_STYLE: dict[str, str] = {
    "upColor": "#26a69a",
    "downColor": "#ef5350",
    "borderUpColor": "#26a69a",
    "borderDownColor": "#ef5350",
    "wickUpColor": "#26a69a",
    "wickDownColor": "#ef5350",
}


def _auto_color(index: int) -> str:
    """Return a distinct hex color using golden-angle hue distribution."""
    hue = (index * 137.508) % 360
    return f"hsl({hue:.1f}, 65%, 55%)"


_COLOR_OPTIONS: dict[str, str] = {
    "line": "color",
    "area": "lineColor",
    "histogram": "color",
    "baseline": "lineColor",
}


# ── internal data model ──────────────────────────────────────────────

class _Series:
    __slots__ = ("kind", "data", "name", "color", "options")
    def __init__(
        self,
        kind: str,
        data: list[dict[str, Any]],
        name: str,
        color: str,
        options: dict[str, Any] | None = None,
    ):
        self.kind = kind
        self.data = data
        self.name = name
        self.color = color
        self.options = options or {}


class _Pane:
    __slots__ = ("height", "bar_times", "candles", "series", "markers", "volume_data")

    def __init__(self, height: int | None = None):
        self.height = height
        self.bar_times: list[str | int] = []
        self.candles: list[dict[str, Any]] | None = None
        self.series: list[_Series] = []
        self.markers: list[dict[str, Any]] | None = None
        self.volume_data: list[dict[str, Any]] | None = None


# ── public API ───────────────────────────────────────────────────────

class Chart:
    """Self-contained Lightweight Charts HTML generator.

    Parameters
    ----------
    width:
        Chart width in pixels.
    height:
        Total height of the chart area.
    title:
        HTML page title.
    ticker:
        Symbol ticker displayed in the chart legend.
    palette:
        Optional list of hex colors to cycle through for series.
        Falls back to golden-angle auto-colors when None.
    main_height:
        Height of the main (first) pane in pixels.
        If None, uses the full *height*.
    """

    def __init__(
        self,
        width: int = 1200,
        height: int = 700,
        title: str = "",
        ticker: str = "",
        palette: list[str] | None = None,
        main_height: int | None = None,
    ):
        self._width = width
        self._height = height
        self._title = title
        self._ticker = ticker
        self._palette = palette
        self._color_index = 0
        self._panes: list[_Pane] = [_Pane(height=main_height or height)]
        self._pane_sizes: list[int] = []
        self._auto_height = main_height is None
        self._bar_times: list[str | int] | None = None

    def set_candles(
        self,
        bars: list[dict[str, Any]],
        *,
        timeframe: str | None = None,
        pane: int = 0,
    ) -> None:
        """Set OHLCV candle data for a pane.

        *bars* accepts either ``OHLCVBar`` dicts (with ``timestamp`` key)
        or pre-formatted dicts with a ``time`` key.
        """
        times, candles, volumes = _extract_bars(bars, timeframe)
        if self._bar_times is None:
            self._bar_times = times
        p = self._panes[pane]
        p.bar_times = times
        p.candles = candles
        if any(v > 0 for v in volumes):
            p.volume_data = [
                {"time": times[i], "value": volumes[i], "color": (
                    "#26a69a" if candles[i]["close"] >= candles[i]["open"]
                    else "#ef5350"
                )}
                for i in range(len(candles))
            ]

    def add_line(
        self,
        values: list[float | None],
        name: str = "",
        color: str | None = None,
        *,
        pane: int = 0,
        line_width: int = 2,
        **kwargs: Any,
    ) -> None:
        """Add a line series (SMA, RSI, etc.) aligned to candle timestamps."""
        self._add_series("line", values, name, color, pane, lineWidth=line_width, **kwargs)

    def add_histogram(
        self,
        values: list[float | None],
        name: str = "",
        color: str | None = None,
        *,
        pane: int = 0,
        colors: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Add a histogram series (volume, MACD histogram).

        *colors* can override per-bar color.
        """
        self._add_series("histogram", values, name, color, pane,
                         per_bar_colors=colors, **kwargs)

    def add_area(
        self,
        values: list[float | None],
        name: str = "",
        color: str | None = None,
        *,
        pane: int = 0,
        line_width: int = 2,
        top_color: str | None = None,
        bottom_color: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Add an area series (filled bands)."""
        opts = dict(lineWidth=line_width)
        if top_color:
            opts["topColor"] = top_color
        if bottom_color:
            opts["bottomColor"] = bottom_color
        self._add_series("area", values, name, color, pane, **opts, **kwargs)

    def add_baseline(
        self,
        values: list[float | None],
        name: str = "",
        color: str | None = None,
        *,
        pane: int = 0,
        base_value: float = 0.0,
        top_color: str = "rgba(255,166,0,0.3)",
        bottom_color: str = "rgba(255,166,0,0.1)",
        **kwargs: Any,
    ) -> None:
        """Add a baseline series (oscillators around a center value)."""
        self._add_series("baseline", values, name, color, pane,
                         baseValue={"type": "price", "price": base_value},
                         topFillColor1=top_color,
                         topFillColor2=top_color,
                         bottomFillColor1=bottom_color,
                         bottomFillColor2=bottom_color,
                         **kwargs)

    def add_markers(
        self,
        markers: list[dict[str, Any]],
        *,
        pane: int = 0,
    ) -> None:
        """Add event markers on the candle series.

        Each marker::

            {"time": "2024-01-15", "position": "aboveBar",
             "color": "#e91e63", "shape": "arrowDown", "text": "Death Cross"}
        """
        self._panes[pane].markers = markers

    def add_pane(self, height: int = 150) -> int:
        """Add a new pane below existing ones. Returns the pane index."""
        idx = len(self._panes)
        p = _Pane(height=height)
        if self._bar_times is not None:
            p.bar_times = list(self._bar_times)
        self._panes.append(p)
        return idx

    def render(self) -> str:
        """Return a self-contained HTML page with the chart."""
        parts: list[str] = [
            '<!DOCTYPE html>',
            '<html lang="en">',
            '<head>',
            '<meta charset="UTF-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
            f'<title>{_escape_html(self._title)}</title>',
            '<script src="https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script>',
        '<style>',
        '  * { margin: 0; padding: 0; box-sizing: border-box; }',
        '  body { background: #11171C; font-family: -apple-system, sans-serif; display: flex; justify-content: center; }',
        '  .chart-wrap { width: ' + str(self._width) + 'px; display: flex; flex-direction: row; }',
        '  .chart-ticker { color: #E8ECF0; padding: 12px 0 4px; font-size: 15px; font-weight: 600; }',
        '</style>',
        '</head>',
        '<body>',
        ]

        if self._ticker:
            parts.append(f'<div class="chart-ticker">{_escape_html(self._ticker)}</div>')

        parts.append('<div class="chart-wrap">')
        parts.append('<div class="chart-panes">')

        scripts: list[str] = []
        for i, pane in enumerate(self._panes):
            height = pane.height if pane.height else self._height
            parts.append(f'<div id="chart{i}" style="width:100%;height:{height}px"></div>')
            scripts.append(self._pane_js(i, pane))

        parts.append('</div>')
        parts.append('<div class="chart-legends">')
        for i, pane in enumerate(self._panes):
            height = pane.height if pane.height else self._height
            parts.append(self._pane_legend_html(i, height=height))
        parts.append('</div>')
        parts.append('</div>')
        parts.append('\n'.join(self._LEGEND_CSS))

        parts.append('<script>\n' + '\n\n'.join(scripts) + '\n</script>')
        if len(self._panes) > 1:
            parts.append('<script>\n' + self._sync_js() + '\n</script>')
        parts.append('<script>\n' + self._controls_js() + '\n</script>')
        parts.extend(['</body>', '</html>'])
        return '\n'.join(parts)

    def save(self, path: str) -> None:
        """Render and write the HTML page to *path*."""
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.render())

    # ── legend ─────────────────────────────────────────────────────

    def _series_data_for_legend(self) -> list[dict]:
        """Return per-pane lists of series metadata for legend rendering."""
        result = []
        for pane in self._panes:
            items = []
            for s in pane.series:
                last_val = None
                if s.data:
                    for pt in reversed(s.data):
                        if "value" in pt:
                            last_val = pt["value"]
                            break
                items.append({
                    "kind": s.kind,
                    "name": s.name,
                    "color": s.color,
                    "last_value": last_val,
                })
            result.append({
                "has_candles": pane.candles is not None,
                "bar_count": len(pane.candles) if pane.candles else 0,
                "series": items,
            })
        return result

    def _pane_legend_inner_html(self, pane_idx: int, top_px: int | None = None) -> str:
        """Return legend rows for the given pane index (no outer wrapper)."""
        pane_data = self._series_data_for_legend()[pane_idx]
        lines = []
        for j, s in enumerate(pane_data["series"]):
            last_val = s["last_value"]
            val_str = f"{last_val:.2f}" if last_val is not None else ""
            lines.append(f'  <div class="tv-legend-row" data-series="s{pane_idx}_{j}">')
            lines.append(f'    <span class="tv-legend-eye" data-visible="1">\U0001f441</span>')
            lines.append(f'    <span class="tv-legend-swatch" style="background:{s["color"]}"></span>')
            lines.append(f'    <span class="tv-legend-name">{_escape_html(s["name"])}</span>')
            lines.append(f'    <span class="tv-legend-value">{val_str}</span>')
            lines.append(f'  </div>')
        return '\n'.join(lines)

    def _pane_legend_html(self, pane_idx: int, height: int | None = None) -> str:
        """Return a legend HTML div for the given pane index."""
        h = f"height:{height}px;" if height is not None else ""
        return (
            f'<div id="l{pane_idx}" class="tv-legend" data-pane="{pane_idx}"'
            f' style="{h}">\n'
            f'{self._pane_legend_inner_html(pane_idx)}'
            f'</div>'
        )

    _LEGEND_CSS = [
        '<style>',
        '.chart-panes {',
        '  flex: 1; min-width: 0;',
        '}',
        '.chart-legends {',
        '  width: 220px; display: flex; flex-direction: column;',
        '  padding-left: 8px;',
        '}',
        '.tv-legend {',
        '  background: rgba(17, 23, 28, 0.9);',
        '  border: 1px solid #2A3440;',
        '  border-radius: 6px;',
        '  padding: 8px 12px;',
        '  font-family: -apple-system, monospace;',
        '  font-size: 12px;',
        '  color: #E8ECF0;',
        '  min-width: 180px;',
        '  overflow-y: auto;',
        '  margin-bottom: 4px;',
        '}',
        '.tv-legend:last-child { margin-bottom: 0; }',
        '.tv-legend-header {',
        '  font-size: 13px;',
        '  font-weight: 600;',
        '  margin-bottom: 6px;',
        '  padding-bottom: 4px;',
        '  border-bottom: 1px solid #2A3440;',
        '}',
        '.tv-legend-bars { font-weight: 400; color: #758696; }',
        '.tv-legend-row {',
        '  display: flex; align-items: center;',
        '  gap: 6px; padding: 2px 0;',
        '  cursor: default;',
        '}',
        '.tv-legend-row.hidden { opacity: 0.4; text-decoration: line-through; }',
        '.tv-legend-eye { cursor: pointer; user-select: none; }',
        '.tv-legend-swatch {',
        '  display: inline-block; width: 10px; height: 10px;',
        '  border-radius: 2px; cursor: pointer;',
        '}',
        '.tv-legend-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }',
        '.tv-legend-value { text-align: right; color: #758696; font-variant-numeric: tabular-nums; }',
        '</style>',
    ]

    def _controls_js(self) -> str:
        """Return an IIFE that enables interactive legend controls and crosshair value tracking."""
        lines: list[str] = []
        lines.append('(function() {')
        lines.append('  var ctx = window.__chartCtx || (window.__chartCtx = {});')
        lines.append('  ctx._chartPanes = {};')

        # ── legend click handler ───────────────────────────
        lines.append('  function setupLegend(paneIdx) {')
        lines.append("    var leg = document.getElementById('l' + paneIdx);")
        lines.append('    if (!leg) return;')
        lines.append("    leg.addEventListener('click', function(e) {")

        # Eye toggle
        lines.append("      var eye = e.target.closest('.tv-legend-eye');")
        lines.append('      if (eye) {')
        lines.append("        var row = eye.closest('.tv-legend-row');")
        lines.append('        var sid = row.dataset.series;')
        lines.append('        var entry = ctx[sid];')
        lines.append('        if (entry) {')
        lines.append('          entry.visible = !entry.visible;')
        lines.append('          entry.series.applyOptions({ visible: entry.visible });')
        lines.append("          row.classList.toggle('hidden', !entry.visible);")
        lines.append('        }')
        lines.append('        return;')
        lines.append('      }')

        # Color swatch
        lines.append("      var swatch = e.target.closest('.tv-legend-swatch');")
        lines.append('      if (swatch) {')
        lines.append("        var row = swatch.closest('.tv-legend-row');")
        lines.append('        var sid = row.dataset.series;')
        lines.append('        var entry = ctx[sid];')
        lines.append('        if (!entry) return;')
        lines.append("        var picker = document.createElement('input');")
        lines.append("        picker.type = 'color';")
        lines.append('        picker.value = entry.color;')
        lines.append("        picker.addEventListener('input', function() {")
        lines.append('          var c = picker.value;')
        lines.append('          swatch.style.background = c;')
        lines.append('          entry.color = c;')
        lines.append('          var opts = {};')
        lines.append('          if (entry.baseline) {')
        lines.append('            opts.topLineColor = c;')
        lines.append('            opts.bottomLineColor = c;')
        lines.append('          } else {')
        lines.append('            opts[entry.colorKey] = c;')
        lines.append('          }')
        lines.append('          entry.series.applyOptions(opts);')
        lines.append('        });')
        lines.append("        picker.addEventListener('blur', function() {")
        lines.append('          if (picker.parentNode) picker.parentNode.removeChild(picker);')
        lines.append('        });')
        lines.append('        document.body.appendChild(picker);')
        lines.append('        picker.click();')
        lines.append('      }')

        lines.append('    });')
        lines.append('  }')

        # ── register series and build chart-pane index ─────
        pane_count = len(self._panes)
        for i, pane in enumerate(self._panes):
            series_ids: list[str] = []
            if pane.candles:
                lines.append(f"  ctx['cs{i}'] = {{ visible: true, series: cs{i} }};")
                series_ids.append(f"cs{i}")
            for j, s in enumerate(pane.series):
                color_key = _COLOR_OPTIONS.get(s.kind, "color")
                sid = f"s{i}_{j}"
                is_base = s.kind == "baseline"
                # Store last value for crosshair leave
                last_v = s.data[-1].get("value") if s.data else None
                last_repr = f"{last_v:.2f}" if last_v is not None else "''"
                lines.append(
                    f"  ctx['{sid}'] = {{ visible: true, series: {sid},"
                    f" colorKey: '{color_key}', color: '{s.color}'"
                    f"{', baseline: true' if is_base else ''}"
                    f", _lastVal: {last_repr} }};"
                )
                series_ids.append(sid)
            ids_json = json.dumps(series_ids)
            lines.append(f"  ctx._chartPanes[{i}] = {ids_json};")
            lines.append(f"  setupLegend({i});")

        # ── crosshair value tracking ───────────────────────
        for i in range(pane_count):
            lines.append(f'  (function(chIdx) {{')
            lines.append('    var chart = window["chart" + chIdx];')
            lines.append('    if (!chart) return;')
            lines.append('    chart.subscribeCrosshairMove(function(param) {')
            lines.append('      var ids = ctx._chartPanes[chIdx];')
            lines.append('      if (!ids) return;')
            lines.append('      var leg = document.getElementById("l" + chIdx);')
            lines.append('      if (!leg) return;')
            lines.append('      var isLeaving = !param.point || !param.time;')
            lines.append('      ids.forEach(function(sid) {')
            lines.append('        var entry = ctx[sid];')
            lines.append('        if (!entry || entry.series === undefined) return;')
            lines.append('        var row = leg.querySelector(\'[data-series="\' + sid + \'"]\');')
            lines.append('        if (!row) return;')
            lines.append('        var valEl = row.querySelector(".tv-legend-value");')
            lines.append('        if (!valEl) return;')
            lines.append('        if (isLeaving) {')
            lines.append('          if (entry._lastVal !== undefined)')
            lines.append('            valEl.textContent = entry._lastVal.toFixed(2);')
            lines.append('          else valEl.textContent = "";')
            lines.append('          return;')
            lines.append('        }')
            lines.append('        var data = param.seriesData.get(entry.series);')
            lines.append('        if (data) {')
            lines.append('          var v = data.value !== undefined ? data.value : data.close;')
            lines.append('          if (v !== undefined)')
            lines.append('            valEl.textContent = v.toFixed(2);')
            lines.append('        }')
            lines.append('      });')
            lines.append('    });')
            lines.append('  })(' + str(i) + ');')

        lines.append('})();')
        return '\n'.join(lines)

    def render_body(self) -> str:
        """Return chart divs + embedded script only — no <html>/<head>/<body> wrapper."""
        parts: list[str] = []
        parts.append('<div style="display:flex;flex-direction:row">')
        parts.append('<div class="chart-panes">')
        for i, pane in enumerate(self._panes):
            height = pane.height if pane.height else self._height
            parts.append(f'<div id="chart{i}" style="width:100%;height:{height}px"></div>')
        parts.append('</div>')
        parts.append('<div class="chart-legends">')
        for i, pane in enumerate(self._panes):
            height = pane.height if pane.height else self._height
            parts.append(self._pane_legend_html(i, height=height))
        parts.append('</div>')
        parts.append('</div>')
        parts.append('\n'.join(self._LEGEND_CSS))
        scripts: list[str] = []
        for i, pane in enumerate(self._panes):
            scripts.append(self._pane_js(i, pane))
        parts.append('<script>\n' + '\n\n'.join(scripts) + '\n</script>')
        if len(self._panes) > 1:
            parts.append('<script>\n' + self._sync_js() + '\n</script>')
        parts.append('<script>\n' + self._controls_js() + '\n</script>')
        return '\n'.join(parts)

    # ── helpers ────────────────────────────────────────────────────

    def _next_color(self) -> str:
        idx = self._color_index
        self._color_index += 1
        if self._palette:
            return self._palette[idx % len(self._palette)]
        return _auto_color(idx)

    def _add_series(
        self,
        kind: str,
        values: list[float | None],
        name: str,
        color: str | None,
        pane_idx: int,
        per_bar_colors: list[str] | None = None,
        **options: Any,
    ) -> None:
        if color is None:
            color = self._next_color()
        pane = self._panes[pane_idx]
        times = pane.bar_times
        if not times:
            msg = "Call set_candles() before adding series"
            raise ValueError(msg)

        n = len(times)
        data: list[dict[str, Any]] = []
        for i in range(n):
            v = values[i] if i < len(values) else None
            pt: dict[str, Any] = {"time": times[i]}
            if v is not None:
                pt["value"] = v
                if per_bar_colors and i < len(per_bar_colors) and per_bar_colors[i]:
                    pt["color"] = per_bar_colors[i]
            data.append(pt)

        if not options.get("color"):
            if kind == "line":
                options["color"] = color
            elif kind == "area":
                options.setdefault("lineColor", color)
                options.setdefault("topColor", color)
                options.setdefault("bottomColor", color)
            elif kind == "baseline":
                options.setdefault("topLineColor", color)
                options.setdefault("bottomLineColor", color)
            elif kind == "histogram":
                options.setdefault("color", color)

        pane.series.append(_Series(kind, data, name, color, options))

    def _sync_js(self) -> str:
        """Return JS to sync time scales across multiple panes."""
        pane_count = len(self._panes)
        lines = [
            '(function() {',
            f'  var charts = [{", ".join(f"window.chart{i}" for i in range(pane_count))}];',
            '  var syncing = false;',
            '  function sync(range) {',
            '    if (syncing) return;',
            '    syncing = true;',
            '    for (var i = 0; i < charts.length; i++) {',
            '      var ts = charts[i].timeScale();',
            '      ts.setVisibleLogicalRange(range);',
            '    }',
            '    syncing = false;',
            '  }',
        ]
        for i in range(pane_count):
            lines.append(
                f'  window.chart{i}.timeScale().subscribeVisibleLogicalRangeChange(sync);'
            )
        lines.append('})();')
        return '\n'.join(lines)

    def _pane_js(self, idx: int, pane: _Pane) -> str:
        lines: list[str] = [
            f'(function() {{',
            f'  var chart = window.chart{idx} = LightweightCharts.createChart(',
            f'    document.getElementById("chart{idx}"),',
            f'    {json.dumps(self._chart_options(pane))}',
            f'  );',
        ]

        candle_var: str | None = None
        if pane.candles:
            candle_var = f"cs{idx}"
            lines.append(f'  window.{candle_var} = chart.addSeries(LightweightCharts.CandlestickSeries, {json.dumps(_CANDLE_STYLE)});')
            lines.append(f'  {candle_var}.setData({json.dumps(pane.candles)});')

            if pane.markers:
                lines.append(f'  {candle_var}.setMarkers({json.dumps(pane.markers)});')

        for j, s in enumerate(pane.series):
            var = f"s{idx}_{j}"
            series_type = _SERIES_TYPES[s.kind]
            style = self._series_style(s)
            lines.append(f'  window.{var} = chart.addSeries(LightweightCharts.{series_type}, {json.dumps(style)});')
            lines.append(f'  {var}.setData({json.dumps(s.data)});')

        lines.append('})();')
        return '\n  '.join(lines)

    def _chart_options(self, pane: _Pane) -> dict[str, Any]:
        height = pane.height if pane.height else self._height
        base: dict[str, Any] = {
            "height": height,
        }
        base.update(_CHART_LAYOUT)
        return base

    def _series_style(self, s: _Series) -> dict[str, Any]:
        style: dict[str, Any] = dict(s.options)
        if "title" not in style and s.name:
            style["title"] = s.name
        if "lastValueVisible" not in style:
            style["lastValueVisible"] = False
        if "priceLineVisible" not in style:
            style["priceLineVisible"] = False
        return style


_SERIES_TYPES: dict[str, str] = {
    "line": "LineSeries",
    "histogram": "HistogramSeries",
    "area": "AreaSeries",
    "baseline": "BaselineSeries",
}
