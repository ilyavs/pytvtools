"""Tests for pytvtools_core.chart — the self-contained HTML chart generator."""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

import pytest
from pytvtools_core.chart import Chart, _auto_color, _format_time


# ── helpers ──────────────────────────────────────────────────────────

def sample_bars(n: int = 10) -> list[dict]:
    """Generate *n* OHLCVBar-like dicts with daily timestamps."""
    from datetime import datetime, timezone, timedelta
    base = datetime(2024, 1, 2, tzinfo=timezone.utc)  # Tuesday
    bars = []
    price = 100.0
    for i in range(n):
        t = base + timedelta(days=i)
        bars.append({
            "timestamp": t.timestamp(),
            "open": price,
            "high": price + 2.0,
            "low": price - 1.0,
            "close": price + 0.5,
            "volume": 1000.0 + i * 10,
        })
        price += 0.5 + (i % 3) * 0.3
    return bars


def sample_bars_intraday(n: int = 10) -> list[dict]:
    """Generate *n* OHLCVBar-like dicts with intraday timestamps."""
    from datetime import datetime, timezone, timedelta
    base = datetime(2024, 1, 2, 9, 30, tzinfo=timezone.utc)
    bars = []
    price = 100.0
    for i in range(n):
        t = base + timedelta(minutes=15 * i)
        bars.append({
            "timestamp": t.timestamp(),
            "open": price,
            "high": price + 2.0,
            "low": price - 1.0,
            "close": price + 0.5,
            "volume": 1000.0,
        })
        price += 0.3
    return bars


def assert_renders(chart: Chart) -> str:
    """Assert chart.render() returns valid HTML and return it."""
    html = chart.render()
    assert "<!DOCTYPE html>" in html
    assert "lightweight-charts" in html
    assert "createChart" in html
    assert "setData" in html
    return html


# ── _format_time ─────────────────────────────────────────────────────

class TestFormatTime:
    def test_daily_auto_detect(self):
        # 2024-01-02 00:00:00 UTC
        ts = 1704153600.0
        assert _format_time(ts) == "2024-01-02"

    def test_daily_explicit(self):
        ts = 1704153600.0
        assert _format_time(ts, "D") == "2024-01-02"
        assert _format_time(ts, "W") == "2024-01-02"
        assert _format_time(ts, "M") == "2024-01-02"

    def test_intraday_returns_unix_int(self):
        # 2024-01-02 09:30:00 UTC
        ts = 1704192600.0
        result = _format_time(ts)
        assert isinstance(result, int)
        assert result == 1704192600

    def test_intraday_explicit_timeframe_uses_int(self):
        ts = 1704192600.0
        assert _format_time(ts, "60") == 1704192600
        assert _format_time(ts, "15") == 1704192600


# ── Chart creation ───────────────────────────────────────────────────

class TestChartCreation:
    def test_defaults(self):
        chart = Chart()
        assert chart._width == 1200
        assert chart._height == 700
        assert len(chart._panes) == 1

    def test_custom_size(self):
        chart = Chart(width=800, height=500, title="Test")
        assert chart._width == 800
        assert chart._height == 500
        assert chart._title == "Test"


# ── set_candles ──────────────────────────────────────────────────────

class TestSetCandles:
    def test_with_timestamp_key(self):
        chart = Chart()
        chart.set_candles(sample_bars(5))
        assert len(chart._panes[0].candles) == 5
        assert chart._panes[0].candles[0]["time"] == "2024-01-02"
        assert chart._panes[0].candles[0]["open"] == 100.0
        assert chart._panes[0].candles[0]["close"] == 100.5

    def test_with_preformatted_time(self):
        chart = Chart()
        bars = [
            {"time": "2024-01-02", "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000},
            {"time": "2024-01-03", "open": 101, "high": 103, "low": 100, "close": 102, "volume": 1100},
        ]
        chart.set_candles(bars)
        assert chart._panes[0].candles[0]["time"] == "2024-01-02"

    def test_with_unix_timestamp(self):
        chart = Chart()
        bars = [
            {"time": 1704153600, "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000},
        ]
        chart.set_candles(bars)
        assert chart._panes[0].candles[0]["time"] == 1704153600

    def test_intraday_uses_integer_time(self):
        chart = Chart()
        chart.set_candles(sample_bars_intraday(3))
        for c in chart._panes[0].candles:
            assert isinstance(c["time"], int)

    def test_volume_extracted(self):
        chart = Chart()
        chart.set_candles(sample_bars(3))
        assert chart._panes[0].volume_data is not None
        assert len(chart._panes[0].volume_data) == 3
        assert chart._panes[0].volume_data[0]["value"] == 1000.0

    def test_timeframe_hint(self):
        chart = Chart()
        # intraday timestamps with explicit D timeframe -> force date strings
        bars = sample_bars_intraday(3)
        chart.set_candles(bars, timeframe="D")
        for c in chart._panes[0].candles:
            assert isinstance(c["time"], str)

    def test_specific_pane(self):
        chart = Chart()
        chart.add_pane()
        chart.set_candles(sample_bars(3), pane=1)
        assert len(chart._panes[1].candles) == 3
        assert chart._panes[0].candles is None


# ── add_series ───────────────────────────────────────────────────────

class TestAddSeries:
    def test_add_line(self):
        chart = Chart()
        chart.set_candles(sample_bars(10))
        sma = [None, None] + [100.5 + i * 0.2 for i in range(8)]
        chart.add_line(sma, name="SMA 20", color="#4E5185")
        pane = chart._panes[0]
        assert len(pane.series) == 1
        assert pane.series[0].kind == "line"
        assert pane.series[0].name == "SMA 20"
        assert len(pane.series[0].data) == 10  # None values kept for x-axis alignment

    def test_add_line_errors_without_candles(self):
        chart = Chart()
        with pytest.raises(ValueError, match="set_candles"):
            chart.add_line([1, 2, 3])

    def test_add_histogram(self):
        chart = Chart()
        chart.set_candles(sample_bars(5))
        chart.add_histogram(
            [1000, 1100, 900, 1200, 1000],
            name="Volume",
            color="#1D425C",
            pane=0,
        )
        pane = chart._panes[0]
        assert pane.series[0].kind == "histogram"

    def test_add_histogram_with_per_bar_colors(self):
        chart = Chart()
        chart.set_candles(sample_bars(4))
        colors = ["#f00", "#0f0", "#f00", "#0f0"]
        chart.add_histogram([1, 2, 3, 4], colors=colors)
        data = chart._panes[0].series[0].data
        assert data[0]["color"] == "#f00"
        assert data[1]["color"] == "#0f0"

    def test_add_area(self):
        chart = Chart()
        chart.set_candles(sample_bars(10))
        chart.add_area(
            [100.0 + i * 0.5 for i in range(10)],
            name="BB Upper",
            color="#4E5185",
            top_color="rgba(78,81,133,0.3)",
            bottom_color="rgba(78,81,133,0.05)",
        )
        assert chart._panes[0].series[0].kind == "area"

    def test_add_baseline(self):
        chart = Chart()
        chart.set_candles(sample_bars(10))
        chart.add_baseline(
            [50 + math.sin(i * 0.5) * 10 for i in range(10)],
            color="#FFA600",
            base_value=50,
        )
        assert chart._panes[0].series[0].kind == "baseline"
        assert chart._panes[0].series[0].options["baseValue"] == {"type": "price", "price": 50.0}

    def test_none_values_kept_for_x_axis(self):
        chart = Chart()
        chart.set_candles(sample_bars(5))
        vals = [None, 101.0, None, 103.0, 104.0]
        chart.add_line(vals)
        data = chart._panes[0].series[0].data
        assert len(data) == 5
        has_value = sum(1 for pt in data if "value" in pt)
        assert has_value == 3
        missing = [pt for pt in data if "value" not in pt]
        assert len(missing) == 2
        for pt in missing:
            assert "time" in pt

    def test_exact_time_alignment(self):
        chart = Chart()
        bars = sample_bars(5)
        chart.set_candles(bars)
        # Add half the length — should only align first entries
        chart.add_line([100.0, 101.0])
        data = chart._panes[0].series[0].data
        assert len(data) == 5
        assert data[0]["time"] == "2024-01-02"
        assert data[0]["value"] == 100.0
        assert data[1]["time"] == "2024-01-03"
        assert data[1]["value"] == 101.0
        # Remaining entries have no value (padded for x-axis alignment)
        assert "value" not in data[2]
        assert "value" not in data[3]
        assert "value" not in data[4]


# ── markers ──────────────────────────────────────────────────────────

class TestMarkers:
    def test_add_markers(self):
        chart = Chart()
        chart.set_candles(sample_bars(10))
        chart.add_markers([
            {"time": "2024-01-05", "position": "aboveBar",
             "color": "#e91e63", "shape": "arrowDown", "text": "Event"},
        ])
        assert len(chart._panes[0].markers) == 1
        assert chart._panes[0].markers[0]["shape"] == "arrowDown"

    def test_markers_in_rendered_output(self):
        chart = Chart()
        chart.set_candles(sample_bars(5))
        chart.add_markers([
            {"time": "2024-01-03", "position": "belowBar",
             "color": "#4caf50", "shape": "arrowUp", "text": "Buy"},
        ])
        html = chart.render()
        assert "setMarkers" in html
        assert "arrowUp" in html
        assert "Buy" in html


# ── multi-pane ───────────────────────────────────────────────────────

class TestMultiPane:
    def test_add_pane(self):
        chart = Chart()
        assert len(chart._panes) == 1
        idx = chart.add_pane(height=200)
        assert idx == 1
        assert len(chart._panes) == 2
        assert chart._panes[1].height == 200

    def test_two_panes(self):
        chart = Chart()
        chart.set_candles(sample_bars(5))
        chart.add_pane(height=150)
        chart.set_candles(sample_bars(3), pane=1)
        chart.add_line([100.0, 101.0, 102.0], name="RSI", color="#FFA600", pane=1)
        assert len(chart._panes[0].candles) == 5
        assert len(chart._panes[1].candles) == 3
        assert len(chart._panes[1].series) == 1

    def test_render_two_panes(self):
        chart = Chart()
        chart.set_candles(sample_bars(3))
        chart.add_pane(height=150)
        chart.set_candles(sample_bars(3), pane=1)
        html = assert_renders(chart)
        assert "chart0" in html
        assert "chart1" in html


# ── render ───────────────────────────────────────────────────────────

class TestRender:
    def test_basic_render(self):
        chart = Chart(title="Test Chart")
        chart.set_candles(sample_bars(5))
        chart.add_line([100.0, 101.0], name="SMA", color="#4E5185")
        html = assert_renders(chart)
        assert "Test Chart" in html
        assert "candlestick" in html or "Candlestick" in html

    def test_render_no_data(self):
        chart = Chart()
        html = chart.render()
        assert "createChart" in html
        assert "setData" not in html

    def test_render_json_escaping(self):
        chart = Chart()
        chart.set_candles(sample_bars(2))
        chart.add_line([100.5, 101.0])
        html = chart.render()
        # JS should contain valid JSON arrays for setData
        assert "100.5" in html
        assert "101.0" in html

    def test_save(self):
        chart = Chart()
        chart.set_candles(sample_bars(3))
        chart.add_line([100.0, 101.0, 102.0])
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as f:
            path = f.name
        try:
            chart.save(path)
            saved = Path(path).read_text(encoding="utf-8")
            assert "<!DOCTYPE html>" in saved
            assert "createChart" in saved
        finally:
            Path(path).unlink(missing_ok=True)

    def test_series_names_in_html(self):
        chart = Chart()
        chart.set_candles(sample_bars(5))
        chart.add_line([100.0] * 5, name="SMA 50", color="#4E5185")
        chart.add_histogram([1000] * 5, name="Volume", color="#1D425C")
        html = chart.render()
        assert "SMA 50" in html
        assert "Volume" in html


# ── smoke: all series types via render ───────────────────────────────

class TestAllSeriesTypes:
    def test_all_types_render(self):
        chart = Chart()
        chart.set_candles(sample_bars(10))
        chart.add_line([100.0 + i for i in range(10)], name="Line", color="#FFA600")
        chart.add_area([100.0 + i for i in range(10)], name="Area", color="#4E5185")
        chart.add_baseline([50.0] * 10, name="BL", color="#FFA600", base_value=50)
        chart.add_histogram([1000] * 10, name="Hist", color="#1D425C")
        html = assert_renders(chart)
        # Check each v5 addSeries call appears
        assert "addSeries(LightweightCharts.LineSeries" in html
        assert "addSeries(LightweightCharts.AreaSeries" in html
        assert "addSeries(LightweightCharts.BaselineSeries" in html
        assert "addSeries(LightweightCharts.HistogramSeries" in html


# ── ticker / palette / auto-color ─────────────────────────────────────

class TestTickerPalette:
    def test_ticker_in_chart(self):
        chart = Chart(ticker="AAPL")
        chart.set_candles(sample_bars(5))
        html = chart.render()
        assert "AAPL" in html

    def test_auto_color_distinct(self):
        c1 = _auto_color(0)
        c2 = _auto_color(1)
        assert c1 != c2
        assert c1.startswith("hsl(")
        assert c2.startswith("hsl(")

    def test_palette_cycle(self):
        chart = Chart(palette=["#f00", "#0f0"])
        chart.set_candles(sample_bars(5))
        chart.add_line([1, 2, 3], name="A")
        chart.add_line([4, 5, 6], name="B")
        chart.add_line([7, 8, 9], name="C")
        html = chart.render()
        assert '#f00"' in html or "'#f00'" in html
        assert '#0f0"' in html or "'#0f0'" in html


# ── legend + render_body ─────────────────────────────────────────────

class TestLegendRenderBody:
    def test_legend_in_render(self):
        chart = Chart(ticker="AAPL")
        chart.set_candles(sample_bars(5))
        chart.add_line([1, 2, 3], name="TestLine")
        html = chart.render()
        assert "tv-legend" in html
        assert "AAPL" in html
        assert "TestLine" in html

    def test_render_body_no_wrapper(self):
        chart = Chart()
        chart.set_candles(sample_bars(5))
        body = chart.render_body()
        assert "<!DOCTYPE" not in body
        assert "<html" not in body
        assert "<body" not in body
        assert "chart0" in body
        assert "LightweightCharts.createChart" in body

    def test_render_body_has_legend(self):
        chart = Chart(ticker="AAPL")
        chart.set_candles(sample_bars(5))
        body = chart.render_body()
        assert "tv-legend" in body

    def test_controls_js_present(self):
        chart = Chart()
        chart.set_candles(sample_bars(5))
        chart.add_line([1, 2, 3], name="L")
        html = chart.render()
        assert "applyOptions" in html
        assert "applyOptions" in html

    def test_controls_body_has_js(self):
        chart = Chart()
        chart.set_candles(sample_bars(5))
        body = chart.render_body()
        assert "applyOptions" in body

    def test_controls_ctx_registers_series(self):
        chart = Chart()
        chart.set_candles(sample_bars(5))
        chart.add_line([1, 2, 3], name="L1")
        chart.add_line([4, 5, 6], name="L2")
        html = chart.render()
        assert "__chartCtx" in html
        assert "s0_0" in html
        assert "s0_1" in html

    def test_controls_data_series_matches_ctx(self):
        chart = Chart()
        chart.set_candles(sample_bars(5))
        chart.add_line([1, 2, 3], name="L1")
        html = chart.render()
        assert 'data-series="s0_0"' in html

    def test_legend_inside_pane_wrap(self):
        chart = Chart()
        chart.set_candles(sample_bars(5))
        html = chart.render()
        assert 'tv-legend' in html
        assert 'id="l0"' in html

    def test_multi_pane_legend_per_pane(self):
        chart = Chart()
        chart.set_candles(sample_bars(10))
        p1 = chart.add_pane(height=100)
        chart.add_line([1, 2, 3], name="A", pane=p1)
        html = chart.render()
        assert 'id="l0"' in html
        assert 'id="l1"' in html
        assert 'chart-wrap' in html

    def test_color_picker_appended_to_dom(self):
        chart = Chart()
        chart.set_candles(sample_bars(5))
        chart.add_line([1, 2], name="L")
        html = chart.render()
        assert "appendChild(picker)" in html
        assert "removeChild(picker)" in html
        assert "picker.click()" in html

    def test_series_vars_are_global(self):
        chart = Chart()
        chart.set_candles(sample_bars(5))
        chart.add_line([1, 2], name="L1")
        html = chart.render()
        assert "window.cs0" in html
        assert "window.s0_0" in html
        assert "window.chart0" in html

    def test_ctx_uses_correct_color_key(self):
        chart = Chart()
        chart.set_candles(sample_bars(5))
        chart.add_line([1, 2], name="L")
        chart.add_area([1, 2], name="A")
        chart.add_histogram([1, 2], name="H")
        chart.add_baseline([1, 2], name="B", base_value=50)
        html = chart.render()
        assert "colorKey: 'color'" in html  # line
        assert "colorKey: 'lineColor'" in html  # area
        assert "colorKey: 'color'" in html  # histogram
        assert "colorKey: 'lineColor'" in html  # baseline
