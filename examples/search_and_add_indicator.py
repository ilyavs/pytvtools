"""Search for indicators by keyword and add by study_id — works for built-in and community scripts."""
import asyncio
import logging

from pytvtools import TV, wait_for_cdp

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
        return

    async with TV() as tv:
        state = await tv.get_state()
        log.info(f"Chart: {state}")

        await _ensure_slot(tv)

        # Built-in indicator: search -> add by study_id
        log.info("\n=== Built-in: search 'RSI' ===")
        results = await tv.search_indicators("RSI")
        for r in results[:3]:
            log.info(f"  {r['name']:40s} {r['study_id']:25s} {r.get('publisher', '')}")
        log.info(f"  Adding {results[0]['study_id']}...")
        eid = await tv.add_indicator(results[0]["study_id"])
        log.info(f"  -> entity ID: {eid}")
        await asyncio.sleep(1.5)

        # Community script: search -> add by PUB;id
        await _ensure_slot(tv)
        log.info("\n=== Community: add PUB;85 (DSS Bressert) ===")
        eid = await tv.add_indicator("PUB;85")
        log.info(f"  -> entity ID: {eid}")
        await asyncio.sleep(2)

        # Read values
        log.info("\n=== Indicator values ===")
        vals = await tv.get_study_values()
        for name, data in vals.items():
            values = data.get("values", [])
            if values:
                last = values[-1]
                log.info(f"  {name}: last = {last['value']:.2f}")
            else:
                log.info(f"  {name}: {data}")

        await tv.remove_all_indicators()
        log.info("  Removed all indicators.")

    log.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
