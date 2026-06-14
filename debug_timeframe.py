"""Check exact bar spacing to identify timeframe."""
import asyncio
import logging
from pytvtools import TV

logging.basicConfig(level=logging.INFO)

async def main():
    async with TV() as tv:
        await tv.set_symbol("BINANCE:BTCUSDT")
        await tv.set_timeframe("1D")
        await asyncio.sleep(3)

        info = await tv._eval("""
        (function() {
            var chart = window.TradingViewApi.chart();
            return JSON.stringify({
                resolution: chart.resolution(),
                symbol: chart.symbol()
            });
        })()
        """)
        print(f"Chart state: {info}")

        bars = await tv.get_ohlcv(summary=False)
        print(f"Bars: {len(bars)}")

        # Check spacing of first 10 and last 10 bars
        print("\nFirst 10 bar deltas (seconds):")
        for i in range(1, min(11, len(bars))):
            delta = bars[i]["timestamp"] - bars[i-1]["timestamp"]
            print(f"  bar[{i}]: delta={delta}s ({delta/3600:.1f}h)")

        print("\nMid bar deltas (around index 500):")
        for i in range(500, min(510, len(bars))):
            delta = bars[i]["timestamp"] - bars[i-1]["timestamp"]
            print(f"  bar[{i}]: delta={delta}s ({delta/3600:.1f}h)")

        print("\nLast 10 bar deltas:")
        for i in range(len(bars)-9, len(bars)):
            delta = bars[i]["timestamp"] - bars[i-1]["timestamp"]
            print(f"  bar[{i}]: delta={delta}s ({delta/3600:.1f}h)")

        # Check visible range
        vr = await tv.get_visible_range()
        print(f"\nVisible range: {vr}")

asyncio.run(main())
