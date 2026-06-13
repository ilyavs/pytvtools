"""Add indicators (by display name and by study ID), read values, change inputs."""
import asyncio
import logging

from pytvtools import TV, wait_for_cdp

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


async def main():
    if not await wait_for_cdp(timeout=5):
        log.error("CDP not reachable.")
        return

    async with TV() as tv:
        state = await tv.get_state()
        log.info(f"Chart: {state}")

        if await tv.get_indicator_count() >= 2:
            log.info("Chart at capacity — removing existing indicators...")
            await tv.remove_all_indicators()
            await asyncio.sleep(0.5)

        # Add by display name
        eid = await tv.add_indicator("Relative Strength Index")
        log.info(f"Added RSI by display name, entity ID: {eid}")
        await asyncio.sleep(2)

        # Add by study ID (java type)
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

        for e in (eid, eid2):
            await tv.remove_indicator(e)
        log.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
