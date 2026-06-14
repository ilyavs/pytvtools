import asyncio
from pytvtools import TV

async def main():
    async with TV() as tv:
        await tv.set_symbol("BINANCE:BTCUSDT")
        await tv.set_timeframe("1D")
        await asyncio.sleep(2)
        bars = await tv.get_ohlcv(summary=False)
        print(f"Total bars: {len(bars)}")
        print(f"First: ts={bars[0]['timestamp']}")
        print(f"Last: ts={bars[-1]['timestamp']}")

        max_gap = 0
        gap_idx = -1
        for i in range(1, len(bars)):
            d = bars[i]["timestamp"] - bars[i-1]["timestamp"]
            if d > max_gap:
                max_gap = d
                gap_idx = i

        print(f"Max gap: {max_gap}s ({max_gap/3600:.1f}h) at bar[{gap_idx-1}]-bar[{gap_idx}]")

        print("\nEvery 50th bar:")
        for i in range(0, len(bars), 50):
            print(f"  bar[{i}]: ts={bars[i]['timestamp']} ({bars[i]['timestamp']/86400:.1f} days)")

        # Check bars around the max gap
        print(f"\nBars around max gap (gap at {gap_idx}):")
        for i in range(max(0, gap_idx-3), min(len(bars), gap_idx+3)):
            print(f"  bar[{i}]: ts={bars[i]['timestamp']}")

asyncio.run(main())
