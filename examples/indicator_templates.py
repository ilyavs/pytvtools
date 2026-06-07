"""
Example: list and apply indicator templates from the Technicals tab.
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
    if not await wait_for_cdp(timeout=5):
        log.error("CDP not reachable. Is Chrome running with --remote-debugging-port=9222?")
        sys.exit(1)

    target = await find_tv_target()
    if not target:
        log.warning("No TradingView chart tab found. Open tradingview.com/chart in Chrome.")

    async with TV(port=9222, target=target) as tv:
        # List available templates in the Technicals tab
        templates = await tv.list_templates("technicals")
        log.info(f"Technicals templates ({len(templates)}):")
        for t in templates:
            log.info(f"  {t['name']}: {t['description']}")

        # Apply the Oscillators template
        await tv.remove_all_indicators()
        await tv.apply_template("Oscillators")

        studies = await tv.get_study_values()
        log.info(f"\nApplied Oscillators — indicators: {list(studies.keys())}")

    log.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
