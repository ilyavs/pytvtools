"""Verify RSI parity with positional alignment and all bars."""
import asyncio
import logging
from pytvtools import TV
from pytvtools.indicators import rsi

logging.basicConfig(level=logging.INFO)

async def main():
    async with TV() as tv:
        await tv.set_symbol("BINANCE:BTCUSDT")
        await tv.set_timeframe("1D")

        bars = await tv.get_ohlcv(summary=False)
        print(f"Bars: {len(bars)}")

        eid = await tv.add_indicator("STD;RSI")
        await asyncio.sleep(3)
        data = await tv.get_indicator_data(eid)
        tv_vals = data["plots"][0]["values"]
        print(f"TV RSI values: {len(tv_vals)}")

        closes = [b["close"] for b in bars]
        py_vals = rsi(closes, period=14)

        print(f"Py RSI values: {len(py_vals)}")
        print(f"First bar ts: {bars[0]['timestamp']}, TV first ts: {tv_vals[0]['timestamp']}")
        print(f"Last bar ts: {bars[-1]['timestamp']}, TV last ts: {tv_vals[-1]['timestamp']}")

        matched = 0
        mismatches = []
        min_idx = 0
        while min_idx < len(py_vals) and py_vals[min_idx] is None:
            min_idx += 1

        for i in range(min_idx, len(py_vals)):
            py = py_vals[i]
            tv = tv_vals[i]["value"] if i < len(tv_vals) else None
            if py is None or tv is None:
                continue
            delta = abs(py - tv)
            if delta > 0.01:
                mismatches.append((i, bars[i]["timestamp"], py, tv, delta))
            else:
                matched += 1

        total = len(bars) - min_idx
        rate = matched / total * 100 if total else 0
        print(f"\nTotal: {total}, Matched: {matched} ({rate:.1f}%), Mismatches: {len(mismatches)}")
        for m in mismatches[:5]:
            print(f"  bar[{m[0]}] ts={m[1]}: py={m[2]:.6f} tv={m[3]:.6f} delta={m[4]:.6f}")

asyncio.run(main())
