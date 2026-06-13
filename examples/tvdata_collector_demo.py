"""Batch OHLCV collection across symbols/timeframes with parquet/JSON export.

Uses TVDataCollector — no Chrome/CDP needed.  Works from host or Docker.

Usage:
    python examples/tvdata_collector_demo.py

    (from Docker):
    docker exec -w /app docker-pytvtools-1 python examples/tvdata_collector_demo.py
"""

import asyncio
import logging
import sys
from pathlib import Path

from pytvtools import TVDataCollector

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


async def main() -> None:
    symbols = [
        "SP:SPX",
        "COINBASE:BTCUSD",
        "NASDAQ:AAPL",
        "FOREXCOM:EURUSD",
        "NYMEX:CL1!",
    ]

    collector = TVDataCollector(
        symbols=symbols,
        timeframes=["1D", "60"],
        bars_count=200,
        max_concurrent=3,
    )

    result = await collector.run()

    print(f"\nResults: {len(result.records)} records, {result.symbols_failed or 'no'} failures")
    for rec in result.records:
        print(f"  {rec['symbol']:<20} {rec['timeframe']:<5} "
              f"close={rec.get('ohlcv_close', '?'):>10}  "
              f"bars={rec.get('ohlcv_bars', '?')}")

    outdir = Path(__file__).parent / "_output"
    outdir.mkdir(exist_ok=True)

    json_path = collector.export_json(outdir / "tvdata_collection.json", overwrite=True)
    print(f"\nJSON: {json_path}")

    try:
        parquet_path = collector.export_parquet(outdir / "tvdata_collection.parquet", overwrite=True)
        print(f"Parquet: {parquet_path}")
    except ImportError:
        print("Parquet export requires: pip install pytvtools[full]")

    return result


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(len(result.symbols_failed) > 0)
