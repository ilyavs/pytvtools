"""Test batch with 20 symbols to verify rate-limit recovery."""
import asyncio
import logging
from pytvtools import TV, wait_for_cdp

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

SYMBOLS = [
    "NASDAQ:AAPL", "NASDAQ:NVDA", "NASDAQ:TSLA", "NASDAQ:MSFT", "NASDAQ:GOOGL",
    "NASDAQ:AMZN", "NASDAQ:META", "NASDAQ:AMD", "NASDAQ:INTC", "NASDAQ:NFLX",
    "NASDAQ:ADBE", "NASDAQ:CSCO", "NASDAQ:CMCSA", "NASDAQ:PEP", "NASDAQ:COST",
    "NASDAQ:AVGO", "NASDAQ:TXN", "NASDAQ:QCOM", "NASDAQ:AMAT", "NASDAQ:INTU",
]


async def main():
    await wait_for_cdp(timeout=10)
    async with TV(port=9222) as tv:
        print("Starting batch scan of 20 symbols ...", flush=True)
        results = await tv.batch(SYMBOLS, ["D"], action="ohlcv")
        success = sum(1 for v in results.values() if v.get("D") is not None)
        failed = sum(1 for v in results.values() if v.get("D") is None)
        print(f"\nResults: {success} succeeded, {failed} failed")
        for sym, tfs in results.items():
            d = tfs.get("D")
            if d:
                print(f"  {sym}: close={d.get('close', '?'):>10}  bars={d.get('bars', '?')}")
            else:
                print(f"  {sym}: ---- FAILED (rate-limited) ----")


if __name__ == "__main__":
    asyncio.run(main())
