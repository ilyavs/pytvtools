import asyncio
import logging
from pytvtools import TV

logging.basicConfig(level=logging.INFO)

async def main():
    async with TV() as tv:
        await tv.set_symbol("BINANCE:BTCUSDT")
        await tv.set_timeframe("1D")

        bars = await tv.get_ohlcv(count=500, summary=False)
        print(f"Loaded {len(bars)} bars")

        eid = await tv.add_indicator("STD;Money_Flow")
        print("Entity ID:", eid)

        await asyncio.sleep(3)

        data = await tv.get_indicator_data(eid)
        if data:
            print(f"Data count: {data['count']}")
            for p in data.get("plots", []):
                print(f"  Plot: {p['name']}, values: {len(p['values'])}")
                if p["values"]:
                    print(f"    First 3: {p['values'][:3]}")
                    print(f"    Last 3: {p['values'][-3:]}")

asyncio.run(main())
