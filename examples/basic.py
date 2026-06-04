"""
Minimal example: connect to TradingView, read chart state + OHLCV + indicators.
"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pytvtools import TV, wait_for_cdp, find_tv_target

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


async def main():
    # Make sure Chrome is running with --remote-debugging-port=9222
    if not await wait_for_cdp(timeout=5):
        log.error("CDP not reachable. Is Chrome running with --remote-debugging-port=9222?")
        sys.exit(1)

    target = await find_tv_target()
    if not target:
        log.warning("No TradingView chart tab found. Open tradingview.com/chart in Chrome.")

    async with TV(port=9222, target=target) as tv:
        # Read chart state
        state = await tv.get_state()
        log.info(f"Chart: {state}")

        # Read OHLCV summary
        ohlcv = await tv.get_ohlcv(count=100, summary=True)
        log.info(f"OHLCV: {ohlcv}")

        # Read study values
        studies = await tv.get_study_values()
        for name, vals in list(studies.items())[:5]:
            log.info(f"  {name}: {vals}")

    log.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
