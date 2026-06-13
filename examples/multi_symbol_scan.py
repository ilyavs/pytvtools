"""Scan multiple symbols and timeframes for indicator values using batch()."""
import asyncio
import logging

from pytvtools import TV, wait_for_cdp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

WATCHLIST = ["NASDAQ:AAPL", "NASDAQ:NVDA", "NASDAQ:TSLA", "BITSTAMP:BTCUSD"]
TIMEFRAMES = ["D", "60"]


async def main():
    await wait_for_cdp(timeout=10)

    async with TV() as tv:
        results = await tv.batch(WATCHLIST, TIMEFRAMES, action="studies")
        for symbol, tfs in results.items():
            for tf, studies in tfs.items():
                rsi = studies.get("Relative Strength Index", {})
                log.info(f"{symbol} ({tf}) — RSI: {rsi}")

    log.info("Scan complete.")


if __name__ == "__main__":
    asyncio.run(main())
