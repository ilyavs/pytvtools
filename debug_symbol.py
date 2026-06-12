"""Debug: test BATS:NVDA symbol switching."""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pytvtools import TV, wait_for_cdp

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


async def main():
    await wait_for_cdp(timeout=10)
    async with TV(port=9222) as tv:
        state = await tv.get_state()
        sym = state["symbol"]
        log.info(f"Initial: {sym}")

        # Switch away and back to the original symbol
        await tv.set_symbol("NASDAQ:AAPL")
        log.info(f"After AAPL: {(await tv.get_state())['symbol']}")

        try:
            await tv.set_symbol(sym)
            log.info(f"Restored: {(await tv.get_state())['symbol']}")
        except Exception as e:
            log.error(f"Restore FAIL: {e}")

        # Now test BITSTAMP:BTCUSD in isolation
        try:
            await tv.set_symbol("BITSTAMP:BTCUSD")
            log.info(f"BTCUSD: {(await tv.get_state())['symbol']}")
        except Exception as e:
            log.error(f"BTCUSD FAIL: {e}")


if __name__ == "__main__":
    asyncio.run(main())
