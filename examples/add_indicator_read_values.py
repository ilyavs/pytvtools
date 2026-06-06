"""
Add an indicator using a search keyword or display name.
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
        log.error("CDP not reachable.")
        sys.exit(1)

    async with TV(port=9222) as tv:
        state = await tv.get_state()
        log.info(f"Chart: {state}")

        # Clear existing indicators if at capacity
        if await tv.get_indicator_count() >= 2:
            log.info("Chart at capacity — removing existing indicators...")
            await tv.remove_all_indicators()
            await asyncio.sleep(0.5)

        # --- Method 1: search first, then add by display name ---
        log.info("Searching for 'RSI'...")
        results = await tv.search_indicators("RSI")
        for r in results[:5]:
            log.info(f"  Found: id={r['id']}, name={r['name']}")

        eid = await tv.add_indicator("Relative Strength Index")
        log.info(f"Added RSI by display name, entity ID: {eid}")

        await asyncio.sleep(2)

        # --- Method 2: by study ID directly ---
        eid2 = await tv.add_indicator("Volume@tv-basicstudies")
        log.info(f"Added Volume by study ID, entity ID: {eid2}")

        await asyncio.sleep(2)

        # Read values
        vals = await tv.get_study_values()
        for name, data in vals.items():
            v = data.get("values", [])
            if v:
                last = v[-1]
                log.info(f"{name}: last value = {last['value']:.2f}")

        # Change RSI length
        await tv.set_indicator_inputs(eid, {"length": 7})
        log.info("Set RSI length to 7")
        await asyncio.sleep(2)

        # Clean up
        for e in (eid, eid2):
            await tv.remove_indicator(e)
        log.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
