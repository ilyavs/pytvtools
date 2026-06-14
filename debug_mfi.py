import asyncio
import logging
from pytvtools import TV
from pytvtools.indicators import mfi

logging.basicConfig(level=logging.INFO)

async def main():
    async with TV() as tv:
        await tv.set_symbol("BINANCE:BTCUSDT")
        await tv.set_timeframe("1D")

        bars = await tv.get_ohlcv(count=500, summary=False)
        print(f"Loaded {len(bars)} bars from chart")

        eid = await tv.add_indicator("STD;Money_Flow")
        print("Entity ID:", eid)

        await asyncio.sleep(3)

        data = await tv.get_indicator_data(eid)
        if not data or not data.get("plots"):
            print("No indicator data")
            return

        tv_plot = data["plots"][0]
        print(f"TV plot '{tv_plot['name']}': {len(tv_plot['values'])} values")
        print(f"  First 5 TV values: {tv_plot['values'][:5]}")
        print(f"  Last 5 TV values: {tv_plot['values'][-5:]}")

        # Build TV values by timestamp
        tv_by_ts = {v["timestamp"]: v["value"] for v in tv_plot["values"]}

        # Python MFI
        py_vals = mfi(bars, period=14)
        print(f"Python MFI: {len(py_vals)} values")
        print(f"  First 5 non-None py values:")
        for i, v in enumerate(py_vals):
            if v is not None and i < 20:
                ts = bars[i]["timestamp"]
                tvv = tv_by_ts.get(ts)
                print(f"    bar[{i}] ts={ts} py={v:.6f} tv={tvv}")
                if i >= 19:
                    break

        # Check timestamp alignment
        bar_tss = set(b["timestamp"] for b in bars)
        tv_tss = set(v["timestamp"] for v in tv_plot["values"])
        overlap = bar_tss & tv_tss
        only_bars = bar_tss - tv_tss
        only_tv = tv_tss - bar_tss
        print(f"\nTimestamp overlap: {len(overlap)}")
        print(f"Only in bars: {len(only_bars)}")
        print(f"Only in TV: {len(only_tv)}")
        if only_bars:
            print(f"  Sample bar-only: {list(only_bars)[:3]}")
        if only_tv:
            print(f"  Sample TV-only: {list(only_tv)[:3]}")

asyncio.run(main())
