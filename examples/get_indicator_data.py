"""
Get ALL historical plot data for an indicator (e.g. Bollinger Bands).
"""
import asyncio
import json
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

        await tv.remove_all_indicators()

        # Add Bollinger Bands by study ID
        eid = await tv.add_indicator("BB@tv-basicstudies")
        log.info(f"Added Bollinger Bands, entity ID: {eid}")
        await asyncio.sleep(2)

        # Get ALL indicator data
        data = await tv.get_indicator_data(eid)
        log.info(f"\nIndicator: {data['title']}")
        log.info(f"Total bars: {data['count']}")
        for plot in data["plots"]:
            vals = plot["values"]
            last = vals[-1] if vals else {}
            log.info(f"  Plot '{plot['name']}': {len(vals)} values, last = {last.get('value', 'N/A'):.2f}")

        # Show structure summary
        log.info(f"\nFull data structure ({data['count']} bars x {len(data['plots'])} plots):")
        log.info(json.dumps(data, indent=2, default=str)[:2000])

        await tv.remove_indicator(eid)
        log.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
