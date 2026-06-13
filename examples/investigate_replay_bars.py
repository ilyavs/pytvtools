"""Investigate whether bar-replay mode loads more historical bars.

Hypothesis: TradingView's chart model normally only loads ~500-1000 bars
into memory.  When you enter replay mode at the earliest available date,
the chart may load *all* historical data, making ``get_ohlcv(count=N)``
return many more bars.

Usage:
    docker exec -w /app docker-pytvtools-1 python examples/investigate_replay_bars.py
"""

import asyncio
import logging

from pytvtools import TV, wait_for_cdp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("investigate_replay")

MAX_BARS = 5000
SYMBOL = "BTCUSD"
TIMEFRAME = "1D"


async def main() -> None:
    await wait_for_cdp()

    async with TV() as tv:
        await tv.set_symbol(SYMBOL)
        await tv.set_timeframe(TIMEFRAME)

        # Phase 1: normal bars
        log.info("=== Phase 1: Normal bars (no replay) ===")
        normal = await tv.get_ohlcv(count=MAX_BARS, summary=True)
        if normal:
            log.info("Normal bars loaded: %d (asked for %d)", normal.get("count"), MAX_BARS)
            log.info("Range: %s -> %s (high=%.2f, low=%.2f)",
                     normal.get("open"), normal.get("close"),
                     normal.get("high"), normal.get("low"))
        else:
            log.info("Normal bars: no data returned")

        # Phase 2: enter replay at earliest date
        log.info("=== Phase 2: Start replay at earliest date ===")
        result = await tv.replay_start()
        log.info("Replay start: %s", result)
        if not result.get("success"):
            log.warning("Cannot start replay — skipping phase 3 and 4")
            return

        # Phase 3: bars in replay mode
        log.info("=== Phase 3: Bars in replay mode ===")
        replay = await tv.get_ohlcv(count=MAX_BARS, summary=True)
        if replay:
            log.info("Replay bars loaded: %d (asked for %d)", replay.get("count"), MAX_BARS)
            log.info("Range: %s -> %s (high=%.2f, low=%.2f)",
                     replay.get("open"), replay.get("close"),
                     replay.get("high"), replay.get("low"))
        else:
            log.info("Replay bars: no data returned")

        # Phase 4: comparison
        normal_count = normal.get("count", 0) if normal else 0
        replay_count = replay.get("count", 0) if replay else 0
        delta = replay_count - normal_count
        if delta > 0:
            log.info("=== RESULT: Replay mode loaded %d MORE bars than normal mode (+%d) ===", replay_count, delta)
            log.info("=== CONCLUSION: Use replay mode to get more historical data ===")
        elif delta == 0:
            log.info("=== RESULT: Both modes loaded the same number of bars (%d) ===", normal_count)
            log.info("=== CONCLUSION: Replay mode does NOT increase bar count ===")
        else:
            log.info("=== RESULT: Normal mode loaded MORE bars than replay mode (%d vs %d) ===", normal_count, replay_count)
            log.info("=== CONCLUSION: Replay mode may reduce available bars ===")

        # Phase 5: step through some bars
        log.info("=== Phase 5: Step forward 5 bars ===")
        for i in range(5):
            step_result = await tv.replay_step()
            log.info("Step %d: date=%s", i + 1, step_result.get("current_date"))

        # Phase 6: get bars again after stepping
        log.info("=== Phase 6: Bars after stepping forward ===")
        stepped = await tv.get_ohlcv(count=MAX_BARS, summary=True)
        if stepped:
            log.info("Post-step bars loaded: %d", stepped.get("count"))

        # Cleanup
        await tv.replay_stop()
        log.info("=== Done ===")


if __name__ == "__main__":
    asyncio.run(main())
