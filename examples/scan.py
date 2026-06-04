"""
Multi-symbol scan example: iterate watchlist, read indicators per symbol.
"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pytvtools import TV, wait_for_cdp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

WATCHLIST = ["NASDAQ:AAPL", "NASDAQ:NVDA", "NASDAQ:TSLA", "BITSTAMP:BTCUSD"]


async def main():
    await wait_for_cdp(timeout=10)

    async with TV(port=9222) as tv:
        for symbol in WATCHLIST:
            log.info(f"Scanning {symbol}...")
            await tv.set_symbol(symbol)
            await asyncio.sleep(0.5)

            state = await tv.get_state()
            quote = await tv.get_quote()
            studies = await tv.get_study_values()

            rsi = studies.get("Relative Strength Index", {})
            log.info(f"  {symbol} — {state.get('timeframe')} | RSI: {rsi}")

    log.info("Scan complete.")


if __name__ == "__main__":
    asyncio.run(main())
