"""Get ALL historical plot data for an indicator (e.g. Bollinger Bands)."""
import asyncio
import json
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

        await tv.remove_all_indicators()

        eid = await tv.add_indicator("BB@tv-basicstudies")
        log.info(f"Added Bollinger Bands, entity ID: {eid}")
        await asyncio.sleep(2)

        data = await tv.get_indicator_data(eid)
        log.info(f"\nIndicator: {data['title']}")
        log.info(f"Total bars: {data['count']}")
        for plot in data["plots"]:
            vals = plot["values"]
            last = vals[-1] if vals else {}
            log.info(f"  Plot '{plot['name']}': {len(vals)} values, last = {last.get('value', 'N/A'):.2f}")

        log.info(f"\nFull data structure ({data['count']} bars x {len(data['plots'])} plots):")
        log.info(json.dumps(data, indent=2, default=str)[:2000])

        await tv.remove_indicator(eid)

    log.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
