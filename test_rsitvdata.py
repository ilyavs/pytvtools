"""Test RSI parity using TVData for OHLCV."""
import asyncio
from pytvtools import TV, TVData
from pytvtools.indicators import rsi

async def main():
    async with TVData() as d:
        bars = await d.get_ohlcv("BINANCE:BTCUSDT", "1D", 500)
        print(f"TVData bars: {len(bars)}")
        print(f"First ts: {bars[0]['timestamp']} (midnight? {bars[0]['timestamp'] % 86400 == 0})")
        print(f"Last ts: {bars[-1]['timestamp']} (midnight? {bars[-1]['timestamp'] % 86400 == 0})")

    async with TV() as tv:
        await tv.set_symbol("BINANCE:BTCUSDT")
        await tv.set_timeframe("1D")
        await tv.get_ohlcv(summary=False)

        eid = await tv.add_indicator("STD;RSI")
        await asyncio.sleep(3)
        data = await tv.get_indicator_data(eid)
        tv_vals = data["plots"][0]["values"]
        print(f"TV RSI: {len(tv_vals)}")
        print(f"First TV ts: {tv_vals[0]['timestamp']}")
        print(f"Last TV ts: {tv_vals[-1]['timestamp']}")

        tv_by_ts = {v["timestamp"]: v["value"] for v in tv_vals}

        closes = [b["close"] for b in bars]
        py_vals = rsi(closes, period=14)

        matched = 0
        mismatches = []
        min_idx = 0
        while min_idx < len(py_vals) and py_vals[min_idx] is None:
            min_idx += 1

        for i in range(min_idx, len(bars)):
            ts = bars[i]["timestamp"]
            py = py_vals[i]
            tv = tv_by_ts.get(ts)
            if py is None or tv is None:
                continue
            delta = abs(py - tv)
            if delta <= 0.01:
                matched += 1
            else:
                mismatches.append((ts, py, tv, delta))

        total = len(bars) - min_idx
        rate = matched / total * 100 if total else 0
        print(f"\nTotal: {total}, Matched: {matched} ({rate:.1f}%), Mismatches: {len(mismatches)}")
        for m in mismatches[:5]:
            print(f"  ts={m[0]}: py={m[1]:.6f} tv={m[2]:.6f} delta={m[3]:.6f}")

asyncio.run(main())
