import asyncio
import logging
from pytvtools import TV

logging.basicConfig(level=logging.INFO)

async def main():
    async with TV() as tv:
        await tv.set_symbol("BINANCE:BTCUSDT")
        await tv.set_timeframe("1D")

        bars = await tv.get_ohlcv(summary=False)
        print(f"All bars: {len(bars)}")
        print(f"  First bar ts: {bars[0]['timestamp']} ({bars[0]['timestamp']/86400:.1f} days from epoch)")
        print(f"  Last bar ts: {bars[-1]['timestamp']} ({bars[-1]['timestamp']/86400:.1f} days from epoch)")

        eid = await tv.add_indicator("STD;Money_Flow")
        await asyncio.sleep(3)
        data = await tv.get_indicator_data(eid)
        tv_vals = data["plots"][0]["values"]
        print(f"\nTV MFI values: {len(tv_vals)}")
        print(f"  First: ts={tv_vals[0]['timestamp']} ({tv_vals[0]['timestamp']/86400:.1f} days), val={tv_vals[0]['value']}")
        print(f"  Last: ts={tv_vals[-1]['timestamp']} ({tv_vals[-1]['timestamp']/86400:.1f} days), val={tv_vals[-1]['value']}")

        # Check timestamp alignment for last 20 bars
        print("\nLast 10 bar timestamps vs TV:")
        for b in bars[-10:]:
            bt = b["timestamp"]
            # Find closest TV value
            tv_match = next((v for v in tv_vals if v["timestamp"] == bt), None)
            print(f"  bar ts={bt}, tv_match={'YES' if tv_match else 'NO'}")

        # Check the 10 bar timestamps that DID match
        bar_tss = set(b["timestamp"] for b in bars)
        tv_tss = set(v["timestamp"] for v in tv_vals)
        overlap = bar_tss & tv_tss
        print(f"\nOverlap count: {len(overlap)}")
        if overlap:
            print(f"  Sample overlapping: {sorted(overlap)[-5:]}")

        # Find timestamps in bars near the end but not in TV
        not_in_tv = [b["timestamp"] for b in bars[-20:] if b["timestamp"] not in tv_tss]
        if not_in_tv:
            print(f"\nRecent bars not in TV data: {not_in_tv}")

asyncio.run(main())
