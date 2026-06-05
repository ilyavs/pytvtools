"""
Add an indicator to the chart and read its current values.
"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pytvtools import TV, wait_for_cdp

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


async def main():
    if not await wait_for_cdp(timeout=5):
        log.error("CDP not reachable. Is Chrome running with --remote-debugging-port=9222?")
        sys.exit(1)

    async with TV(port=9222) as tv:
        state = await tv.get_state()
        log.info(f"Chart: {state}")

        # Add RSI
        eid = await tv.add_indicator("RSI@tv-basicstudies")
        log.info(f"Added RSI, entity ID: {eid}")

        # Wait for data to populate
        await asyncio.sleep(3)

        # Read indicator values
        vals = await tv.get_study_values()
        for name, data in vals.items():
            v = data.get("values", [])
            if v:
                last = v[-1]
                log.info(f"{name}: {len(v)} bars, last RSI = {last['value']:.2f} at ts {last['timestamp']}")
            else:
                log.info(f"{name}: {data}")

        # Clean up
        await tv.remove_indicator(eid)
        log.info("Removed RSI. Done.")


if __name__ == "__main__":
    asyncio.run(main())
