"""Connect to TradingView, read chart state, OHLCV summary, and indicator values."""
import asyncio
import logging

from pytvtools import TV, wait_for_cdp

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


async def main():
    if not await wait_for_cdp(timeout=5):
        log.error("CDP not reachable. Is Chrome running with --remote-debugging-port=9222?")
        return

    async with TV() as tv:
        state = await tv.get_state()
        log.info(f"Chart: {state}")

        ohlcv = await tv.get_ohlcv(count=100, summary=True)
        log.info(f"OHLCV: {ohlcv}")

        studies = await tv.get_study_values()
        for name, vals in list(studies.items())[:5]:
            log.info(f"  {name}: {vals}")

    log.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
