"""
Search for indicators and add by study_id — works for both built-in and community scripts.

Flow: search by keyword → pick from results → add by study_id.
"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pytvtools import TV, TooManyIndicatorsError, wait_for_cdp

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


async def _ensure_slot(tv: TV) -> None:
    count = await tv.get_indicator_count()
    if count >= 2:
        log.info("Chart at capacity — removing existing indicators...")
        await tv.remove_all_indicators()
        await asyncio.sleep(0.5)


async def main():
    if not await wait_for_cdp(timeout=5):
        log.error("CDP not reachable.")
        sys.exit(1)

    async with TV(port=9222) as tv:
        state = await tv.get_state()
        log.info(f"Chart: {state}")

        await _ensure_slot(tv)

        # ------------------------------------------------------------------
        # 1. Built-in indicator: search → add by @tv-basicstudies
        # ------------------------------------------------------------------
        log.info("\n=== Built-in: search 'RSI' ===")
        results = await tv.search_indicators("RSI")
        for r in results[:3]:
            pub = r.get("publisher", "")
            log.info(f"  {r['name']:40s} {r['study_id']:25s} {pub}")

        log.info("  Adding RSI@tv-basicstudies...")
        eid = await tv.add_indicator("RSI@tv-basicstudies")
        log.info(f"  -> entity ID: {eid}")
        await asyncio.sleep(1.5)

        # ------------------------------------------------------------------
        # 2. Community script: search → add by PUB;id
        # ------------------------------------------------------------------
        log.info("\n=== Community: search 'DSS Bressert' ===")
        results = await tv.search_indicators("DSS Bressert")
        for r in results[:3]:
            pub = r.get("publisher", "")
            log.info(f"  {r['name']:55s} {r['study_id']:25s} {pub}")

        await _ensure_slot(tv)

        log.info("  Adding PUB;85...")
        eid = await tv.add_indicator("PUB;85")
        log.info(f"  -> entity ID: {eid}")
        await asyncio.sleep(2)

        # ------------------------------------------------------------------
        # 3. Read values
        # ------------------------------------------------------------------
        log.info("\n=== Indicator values ===")
        vals = await tv.get_study_values()
        for name, data in vals.items():
            values = data.get("values", [])
            if values:
                last = values[-1]
                log.info(f"  {name}: last = {last['value']:.2f}")
            else:
                log.info(f"  {name}: {data}")

        # ------------------------------------------------------------------
        # 4. Clean up
        # ------------------------------------------------------------------
        log.info("\n=== Clean up ===")
        await tv.remove_all_indicators()
        log.info("  Removed all indicators.")

    log.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
