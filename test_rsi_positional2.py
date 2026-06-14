"""Check if RSI matches by position with ALL bars."""
import asyncio
from pytvtools import TV
from pytvtools.indicators import rsi

async def main():
    async with TV() as tv:
        await tv.set_symbol("BINANCE:BTCUSDT")
        await tv.set_timeframe("1D")
        
        # Get ALL bars
        bars = await tv.get_ohlcv(summary=False)
        print(f"Bars: {len(bars)}")
        
        # Add RSI indicator
        eid = await tv.add_indicator("STD;RSI")
        await asyncio.sleep(3)
        
        data = await tv.get_indicator_data(eid)
        tv_vals = data["plots"][0]["values"]
        print(f"TV RSI: {len(tv_vals)}")
        
        # Check first and last timestamps
        print(f"First bar: ts={bars[0]['timestamp']}, First TV: ts={tv_vals[0]['timestamp']}")
        print(f"Last bar: ts={bars[-1]['timestamp']}, Last TV: ts={tv_vals[-1]['timestamp']}")
        
        # Compute RSI
        closes = [b["close"] for b in bars]
        py_vals = rsi(closes, period=14)
        print(f"Py RSI: {len(py_vals)}")
        
        # Align: both arrays should be same length, compare positionally
        offset = len(tv_vals) - len(py_vals)
        print(f"Offset (leading TV bars): {offset}")
        
        matched = 0
        mismatches = []
        min_idx = 0
        while min_idx < len(py_vals) and py_vals[min_idx] is None:
            min_idx += 1
        
        for i in range(min_idx, len(py_vals)):
            py = py_vals[i]
            ti = i + offset
            if ti < 0 or ti >= len(tv_vals):
                continue
            tv = tv_vals[ti]["value"]
            if py is None or tv is None:
                continue
            delta = abs(py - tv)
            if delta <= 0.01:
                matched += 1
            else:
                mismatches.append((bars[i]["timestamp"], py, tv, delta))
        
        total = len(bars) - min_idx
        rate = matched / total * 100 if total else 0
        print(f"\nTotal: {total}, Matched: {matched} ({rate:.1f}%), Mismatches: {len(mismatches)}")
        for m in mismatches[:5]:
            print(f"  ts={m[0]}: py={m[1]:.6f} tv={m[2]:.6f} delta={m[3]:.6f}")

asyncio.run(main())
