"""Demo: full collector pipeline — fetch symbols, export to parquet.

Prerequisites:
    - Running Chrome with TradingView (docker compose up)

Usage:
    python examples/collector_demo.py

Output:
    Writes scan_output/data.parquet with flat records.
"""

import asyncio
import logging
from pathlib import Path

import pyarrow.parquet as pq

from pytvtools import TV, Collector, CollectorConfig, wait_for_cdp
from pytvtools.watchlists import SPDR_SECTORS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("collector_demo")


TIMEFRAMES = ["1D", "60", "15"]

OUTPUT_DIR = Path("scan_output")


async def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    await wait_for_cdp()

    config = CollectorConfig(
        symbols=list(SPDR_SECTORS),
        timeframes=TIMEFRAMES,
        actions=["ohlcv", "studies"],
    )
    collector = Collector(config)

    async with TV() as tv:
        result = await collector.run(tv)

    if not result.records:
        log.warning("No records produced — collection may have failed entirely.")
        return

    log.info(
        "Records: %d | Failed: %d/%d | Duration: %.1fs",
        len(result.records),
        len(result.symbols_failed),
        result.symbols_total,
        (result.end_ts - result.start_ts).total_seconds(),
    )

    path = collector.export_parquet(OUTPUT_DIR / "data.parquet", overwrite=True)
    log.info("Parquet exported: %s", path)

    table = pq.read_table(path)
    log.info("Schema: %s", table.schema)
    log.info("Rows: %d", table.num_rows)
    if table.num_rows:
        row = table.to_pydict()
        sample = {k: v[0] for k, v in row.items()}
        log.info("Sample row: %s", sample)


if __name__ == "__main__":
    asyncio.run(main())
