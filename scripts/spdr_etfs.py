"""Fetch full daily history for all SPDR sector & industry ETFs via TVDataCollector.

Uses the predefined watchlists from pytvtools.watchlists.
Saves parquet + JSON to a directory of your choice.

Usage:
    python scripts/spdr_etfs.py ./spdr_data
    docker exec -w /app docker-pytvtools-1 python scripts/spdr_etfs.py /app/spdr_data
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from pytvtools import TVDataCollector
from pytvtools.watchlists import SPDR_ALL

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# Daily bars: 5000 is the safe limit before WS frame size kicks in (~8000 ceiling).
# SPDR sectors launched Dec 1998 — 5000 bars covers ~20 years of daily data.
BARS_COUNT = 5000
MAX_CONCURRENT = 5

# SPDR_ALL combines SPDR_SECTORS + SPDR_INDUSTRIES
SYMBOLS = list(SPDR_ALL)


async def main(outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"Watchlist: {SPDR_ALL.name} ({len(SYMBOLS)} symbols)")
    print(f"Fetching {BARS_COUNT} daily bars each, concurrency={MAX_CONCURRENT}\n")

    collector = TVDataCollector(
        symbols=SYMBOLS,
        timeframes=["1D"],
        bars_count=BARS_COUNT,
        max_concurrent=MAX_CONCURRENT,
    )

    result = await collector.run()

    print(f"\nCollected {len(result.records)} / {len(SYMBOLS)} ETFs")
    if result.symbols_failed:
        print(f"Failed: {result.symbols_failed}")

    for rec in sorted(result.records, key=lambda r: r["symbol"]):
        sym = rec["symbol"]
        bars = rec.get("ohlcv_bars", 0)
        close = rec.get("ohlcv_close", "?")
        high = rec.get("ohlcv_high", "?")
        low = rec.get("ohlcv_low", "?")
        print(f"  {sym:<6} bars={bars:<5} close={close:>10}  range={high:.0f}-{low:.0f}")

    combined_path = outdir / "spdr_all.parquet"
    collector.export_parquet(combined_path, overwrite=True)
    print(f"\nParquet: {combined_path}")

    json_path = outdir / "spdr_all.json"
    collector.export_json(json_path, overwrite=True)
    print(f"JSON:    {json_path}")

    print(f"\nDone. {len(result.records)} records across {result.symbols_total} symbols.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch SPDR ETF daily history")
    parser.add_argument("outdir", type=Path, help="Output directory for parquet + JSON files")
    args = parser.parse_args()
    asyncio.run(main(args.outdir))
