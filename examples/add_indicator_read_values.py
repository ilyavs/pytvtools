"""
Add an indicator to the chart and read its current values.
"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pytvtools import TV, TooManyIndicatorsError, wait_for_cdp

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


async def ensure_slot(tv: TV) -> None:
    """Remove indicators if the chart is at capacity."""
    try:
        await tv.add_indicator("RSI@tv-basicstudies")
    except TooManyIndicatorsError:
        log.info("Chart at capacity — removing existing indicators...")
        await tv.remove_all_indicators()
        await asyncio.sleep(0.5)


async def main():
    if not await wait_for_cdp(timeout=5):
        log.error("CDP not reachable. Is Chrome running with --remote-debugging-port=9222?")
        sys.exit(1)

    async with TV(port=9222) as tv:
        state = await tv.get_state()
        log.info(f"Chart: {state}")

        count = await tv.get_indicator_count()
        log.info(f"Indicators on chart: {count}")

        # Add RSI (handles capacity limit)
        eid = await tv.add_indicator("RSI@tv-basicstudies")
        log.info(f"Added RSI, entity ID: {eid}")

        await asyncio.sleep(2)

        # Read values with default inputs
        vals = await tv.get_study_values()
        for name, data in vals.items():
            v = data.get("values", [])
            if v:
                last = v[-1]
                log.info(f"{name}: default RSI = {last['value']:.2f}")

        # Change RSI length from 14 to 7
        await tv.set_indicator_inputs(eid, {"length": 7})
        log.info("Set RSI length to 7")
        await asyncio.sleep(2)

        # Read values after input change
        vals = await tv.get_study_values()
        for name, data in vals.items():
            v = data.get("values", [])
            if v:
                last = v[-1]
                log.info(f"{name}: modified RSI = {last['value']:.2f}")

        # Clean up
        await tv.remove_indicator(eid)
        log.info("Removed RSI. Done.")


if __name__ == "__main__":
    asyncio.run(main())
