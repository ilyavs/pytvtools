"""Fetch OHLCV for multiple symbols in parallel via TVData.

Usage:
    docker exec -w /app docker-pytvtools-1 python examples/tvdata_multi.py
"""

import asyncio
import logging

from pytvtools import TVData

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


async def main() -> None:
    symbols = [
        "COINBASE:BTCUSD",
        "COINBASE:ETHUSD",
        "COINBASE:SOLUSD",
        "COINBASE:XRPUSD",
        "COINBASE:ADAUSD",
    ]

    async with TVData() as d:
        results = await d.get_ohlcv_multi(symbols, interval="1D", bars_count=100, summary=True)

    for sym, data in results.items():
        if "error" in data:
            print(f"  {sym}: ERROR — {data['error']}")
        else:
            print(f"  {sym}: close={data['close']:.2f}, volume={data['avg_volume']:.0f}, bars={data['bars']}")


if __name__ == "__main__":
    asyncio.run(main())
