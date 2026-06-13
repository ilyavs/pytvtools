"""Pine Script: open editor, inject source, compile, and read drawings."""
import asyncio
import logging

from pytvtools import TV, wait_for_cdp

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

PINE_SOURCE = """//@version=6
indicator("Test Lines", overlay=true)
plot(close, "Close")
line.new(time, high, time + 100000, low, xloc.bar_time, color=color.blue)
if barstate.islast
    label.new(time, high, "END", color=color.green, textcolor=color.white)
    line.new(time, high, time - 100000, low + 10, xloc.bar_time, color=color.red)
"""


async def main():
    if not await wait_for_cdp(timeout=5):
        log.error("CDP not reachable.")
        return

    async with TV() as tv:
        state = await tv.get_state()
        log.info(f"Chart: {state}")

        if await tv.get_indicator_count() >= 2:
            log.info("Chart at capacity — clearing indicators...")
            await tv.remove_all_indicators()
            await asyncio.sleep(0.5)

        log.info("Opening Pine Editor...")
        try:
            await tv._eval("""
            (function() {
                var btn = document.querySelector('[data-name="open-pine-editor"]');
                if (btn) { btn.click(); return; }
                throw new Error('Pine Editor button not found');
            })()
            """)
            opened = True
        except Exception:
            opened = False
        if not opened:
            log.warning("Pine Editor button not found — skipping Pine operations")
            return
        await asyncio.sleep(1)

        await tv.pine_set_source(PINE_SOURCE)
        await asyncio.sleep(0.5)
        log.info("Source set, compiling...")

        result = await tv.pine_compile()
        log.info(f"Compile result: {result}")
        await asyncio.sleep(2)

        studies = await tv.get_study_values()
        log.info(f"Studies after compile: {list(studies.keys())}")

        lines = await tv.get_pine_lines()
        log.info(f"Pine lines: {len(lines)} found")
        if lines:
            log.info(f"  First line: price={lines[0].get('price')}")

        labels = await tv.get_pine_labels(max_labels=10)
        log.info(f"Pine labels: {len(labels)} found")
        if labels:
            log.info(f"  First label: text={labels[0].get('text')}")

    log.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
