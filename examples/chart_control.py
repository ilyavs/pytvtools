"""
Comprehensive chart control: change timeframe, chart type, scroll, capture.
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
        log.info(f"Start state: {state}")

        await tv.set_timeframe("60")
        await asyncio.sleep(1)
        state = await tv.get_state()
        log.info(f"After set_timeframe(60): {state}")

        await tv.set_chart_type(2)
        await asyncio.sleep(0.5)
        state = await tv.get_state()
        log.info(f"After set_chart_type(Line): {state}")

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
