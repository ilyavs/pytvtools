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

    chart.add_line(sma20, name="SMA 20")
    chart.add_line(sma50, name="SMA 50")
    chart.add_line(ema20, name="EMA 20")

    chart.add_area(bb["upper"], name="BB Upper",
                   top_color="rgba(78,81,133,0.2)", bottom_color="rgba(78,81,133,0.05)")
    chart.add_line(bb["basis"], name="BB Basis", line_width=1)
    chart.add_area(bb["lower"], name="BB Lower",
                   top_color="rgba(78,81,133,0.05)", bottom_color="rgba(78,81,133,0.2)")

    p1 = chart.add_pane(height=160)
    chart.add_histogram(ml["histogram"], name="MACD Hist", pane=p1)
    chart.add_line(ml["macd"], name="MACD", pane=p1)
    chart.add_line(ml["signal"], name="Signal", pane=p1)

    p2 = chart.add_pane(height=130)
    chart.add_baseline(rsi14, name="RSI 14", base_value=50,
                       top_color="rgba(255,166,0,0.15)", bottom_color="rgba(255,166,0,0.05)",
                       pane=p2)

    p3 = chart.add_pane(height=100)
    chart.add_line(atr14, name="ATR 14", pane=p3)

    out = Path(__file__).parent / "demo_chart.html"
    chart.save(str(out))
    print(f"Saved: {out}")
    print(f"  {len(bars)} bars, 4 panes, 10 series")
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
