"""Change timeframe, chart type, scroll to a date, capture a screenshot."""
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
        log.info(f"Start state: {state}")

        await tv.set_timeframe("60")
        await asyncio.sleep(1)
        log.info(f"After set_timeframe(60): {await tv.get_state()}")

        await tv.set_chart_type(2)
        await asyncio.sleep(0.5)
        log.info(f"After set_chart_type(Line): {await tv.get_state()}")

        await tv.set_chart_type(1)
        await asyncio.sleep(0.5)

        await tv.scroll_to_date("2025-01-15")
        await asyncio.sleep(0.5)

        r = await tv.get_visible_range()
        log.info(f"Visible range: {r}")

        q = await tv.get_quote()
        log.info(f"Quote: {q}")

        ss = await tv.capture_screenshot()
        log.info(f"Screenshot: {len(ss)} bytes of base64")

    log.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
