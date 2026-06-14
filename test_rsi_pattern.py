"""Check RSI mismatch pattern — early vs late bars."""
import asyncio
from pytvtools import TV, TVData
from pytvtools.indicators import rsi

async def main():
    async with TVData() as d:
        bars = await d.get_ohlcv("BINANCE:BTCUSDT", "1D", 500)

    async with TV() as tv:
        await tv.set_symbol("BINANCE:BTCUSDT")
        await tv.set_timeframe("1D")
        await tv.get_ohlcv(summary=False)

        eid = await tv.add_indicator("STD;RSI")
        await asyncio.sleep(3)
        data = await tv.get_indicator_data(eid)
        tv_vals = data["plots"][0]["values"]
        tv_by_ts = {int(v["timestamp"]): v["value"] for v in tv_vals}

        closes = [b["close"] for b in bars]
        py_vals = rsi([float(c) for c in closes], period=14)

        min_idx = 0
        while min_idx < len(py_vals) and py_vals[min_idx] is None:
            min_idx += 1

        print("First 10 comparisons:")
        for i in range(min_idx, min(min_idx + 10, len(bars))):
            ts = int(bars[i]["timestamp"])
            py = py_vals[i]
            tv = tv_by_ts.get(ts)
            delta = abs(py - tv) if tv is not None else -1
            print(f"  bar[{i}] ts={ts}: py={py:.4f} tv={tv} delta={delta:.4f}")

        print("\nLast 10 comparisons:")
        for i in range(len(bars) - 10, len(bars)):
            ts = int(bars[i]["timestamp"])
            py = py_vals[i]
            tv = tv_by_ts.get(ts)
            delta = abs(py - tv) if tv is not None else -1
            print(f"  bar[{i}] ts={ts}: py={py:.4f} tv={tv} delta={delta:.4f}")

        # Check if OHLCV from TVData matches chart data
        print("\nComparing OHLCV from TVData vs chart for last 3 bars:")
        chart_bars = await tv.get_ohlcv(count=5, summary=False)
        for cb in chart_bars:
            ct = int(cb["timestamp"])
            # Find matching TVData bar
            for db in bars:
                if int(db["timestamp"]) == ct // 86400 * 86400:
                    print(f"  ts={ct}: chart_close={cb['close']} tvdata_close={db['close']} match={abs(cb['close']-db['close'])<0.01}")
                    break

asyncio.run(main())
