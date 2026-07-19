"""Local demo: fetch AAPL data, compute indicators, render self-contained chart."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pytvtools_core.chart import Chart
from pytvtools_core.indicators import sma, ema, rsi, macd, bbands, atr
from pytvtools_core.tvdata import TVData
import anyio


async def main():
    async with TVData() as d:
        bars = await d.get_ohlcv("NASDAQ:AAPL", "1D", 200)

    symbol = "AAPL"

    sma20 = sma(bars, period=20)
    sma50 = sma(bars, period=50)
    ema20 = ema(bars, period=20)
    rsi14 = rsi(bars, period=14)
    atr14 = atr(bars, period=14)
    bb = bbands(bars, period=20, stddev=2)
    ml = macd(bars, fast=12, slow=26, signal=9)

    chart = Chart(width=1200, height=700, ticker=symbol, title=f"{symbol} — Daily")
    chart.set_candles(bars, timeframe="1D")

    chart.add_line(sma20, name="SMA 20", color="#FF9800")
    chart.add_line(sma50, name="SMA 50", color="#E91E63")
    chart.add_line(ema20, name="EMA 20", color="#2196F3")

    chart.add_line(bb["upper"], name="BB Upper", color="#1565C0")
    chart.add_line(bb["basis"], name="BB Basis", color="#1565C0", line_width=1)
    chart.add_line(bb["lower"], name="BB Lower", color="#1565C0", line_width=1)

    pv = chart.add_pane(height=80)
    volumes = [b["volume"] for b in bars]
    chart.add_histogram(volumes, name="Volume", color="rgba(38,166,154,0.5)", pane=pv)

    p1 = chart.add_pane(height=160)
    chart.add_histogram(ml["histogram"], name="MACD Hist", pane=p1)
    chart.add_line(ml["macd"], name="MACD", color="#2962FF", pane=p1)
    chart.add_line(ml["signal"], name="Signal", color="#FF6D00", pane=p1)

    p2 = chart.add_pane(height=130)
    rsi_ma = sma(rsi14, period=14)
    chart.add_line(rsi14, name="RSI", color="#7B1FA2", pane=p2)
    chart.add_line(rsi_ma, name="RSI MA", color="#FF9800", line_width=1, pane=p2)

    p3 = chart.add_pane(height=100)
    chart.add_line(atr14, name="ATR", color="#FF5722", pane=p3)

    out = Path(__file__).parent / "demo_chart.html"
    chart.save(str(out))
    print(f"Saved: {out}")
    total_series = sum(len(p.series) for p in chart._panes)
    print(f"  {len(bars)} bars, {len(chart._panes)} panes, {total_series} series")
    print(f"  {out.stat().st_size} bytes")

    # Embed the LW library for local use (no CDN dependency)
    lw_path = Path(__file__).parent / "_lightweight_charts.js"
    if lw_path.exists():
        lw_code = lw_path.read_text("utf-8")
        html = out.read_text("utf-8")
        cdn_tag = '<script src="https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script>'
        if cdn_tag in html:
            html = html.replace(cdn_tag, f"<script>\n{lw_code}\n</script>")
            out.write_text(html, "utf-8")
            print(f"  Embedded LW library ({len(lw_code)} bytes) for local use")

    import os
    try:
        os.startfile(str(out))
    except AttributeError:
        import subprocess
        subprocess.run(["open", str(out)], check=False)


anyio.run(main)
