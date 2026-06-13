"""List indicator templates from the Technicals tab and apply one."""
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
        templates = await tv.list_templates("technicals")
        log.info(f"Technicals templates ({len(templates)}):")
        for t in templates:
            log.info(f"  {t['name']}: {t['description']}")

        await tv.remove_all_indicators()
        await tv.apply_template("Oscillators")

        studies = await tv.get_study_values()
        log.info(f"\nApplied Oscillators — indicators: {list(studies.keys())}")

    log.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
