"""Debug MFI by comparing per-bar values with TV."""
import asyncio
import logging
from pytvtools import TV

logging.basicConfig(level=logging.INFO)

async def main():
    async with TV() as tv:
        await tv.set_symbol("BINANCE:BTCUSDT")
        await tv.set_timeframe("1D")

        bars = await tv.get_ohlcv(summary=False)
        print(f"Bars: {len(bars)}")

        eid = await tv.add_indicator("STD;Money_Flow")
        await asyncio.sleep(3)

        data = await tv.get_indicator_data(eid)
        tv_vals = data["plots"][0]["values"]
        print(f"TV MFI values: {len(tv_vals)}")

        offset = len(tv_vals) - len(bars)
        print(f"Offset: {offset}")

        # Compute MFI using Python
        from pytvtools.indicators import mfi
        py_vals = mfi(bars, period=14)

        # Print side-by-side for last 20 non-None values
        print("\nLast 20 bars comparison (py vs tv):")
        count = 0
        for i in range(len(bars) - 1, -1, -1):
            py = py_vals[i]
            tv_i = i + offset
            tv = tv_vals[tv_i]["value"] if 0 <= tv_i < len(tv_vals) else None
            if py is not None and tv is not None:
                ts = bars[i]["timestamp"]
                print(f"  bar[{i}] ts={ts}: py={py:.6f} tv={tv:.6f} delta={abs(py-tv):.6f}")
                count += 1
                if count >= 20:
                    break

        # Try different typical price formulas
        print("\n\nTrying different TP formulas on last 5 bars:")
        for i in range(len(bars) - 5, len(bars)):
            b = bars[i]
            hlc3 = (b["high"] + b["low"] + b["close"]) / 3.0
            ohlc4 = (b["open"] + b["high"] + b["low"] + b["close"]) / 4.0
            hl2 = (b["high"] + b["low"]) / 2.0
            close = b["close"]
            print(f"  bar[{i}]: hlc3={hlc3:.2f} ohlc4={ohlc4:.2f} hl2={hl2:.2f} close={close:.2f} vol={b['volume']:.0f}")

asyncio.run(main())
