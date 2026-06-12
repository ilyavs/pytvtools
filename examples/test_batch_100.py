"""Test CDP batch with 100 symbols."""
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
    "NASDAQ:AAPL", "NASDAQ:NVDA", "NASDAQ:TSLA", "NASDAQ:MSFT", "NASDAQ:GOOGL",
    "NASDAQ:AMZN", "NASDAQ:META", "NASDAQ:AMD", "NASDAQ:INTC", "NASDAQ:NFLX",
    "NASDAQ:ADBE", "NASDAQ:CSCO", "NASDAQ:CMCSA", "NASDAQ:PEP", "NASDAQ:COST",
    "NASDAQ:AVGO", "NASDAQ:TXN", "NASDAQ:QCOM", "NASDAQ:AMAT", "NASDAQ:INTU",
    "NASDAQ:AAPL", "NASDAQ:NVDA", "NASDAQ:TSLA", "NASDAQ:MSFT", "NASDAQ:GOOGL",
    "NASDAQ:AMZN", "NASDAQ:META", "NASDAQ:AMD", "NASDAQ:INTC", "NASDAQ:NFLX",
    "NASDAQ:ADBE", "NASDAQ:CSCO", "NASDAQ:CMCSA", "NASDAQ:PEP", "NASDAQ:COST",
    "NASDAQ:AVGO", "NASDAQ:TXN", "NASDAQ:QCOM", "NASDAQ:AMAT", "NASDAQ:INTU",
    "NASDAQ:AAPL", "NASDAQ:NVDA", "NASDAQ:TSLA", "NASDAQ:MSFT", "NASDAQ:GOOGL",
    "NASDAQ:AMZN", "NASDAQ:META", "NASDAQ:AMD", "NASDAQ:INTC", "NASDAQ:NFLX",
    "NASDAQ:ADBE", "NASDAQ:CSCO", "NASDAQ:CMCSA", "NASDAQ:PEP", "NASDAQ:COST",
    "NASDAQ:AVGO", "NASDAQ:TXN", "NASDAQ:QCOM", "NASDAQ:AMAT", "NASDAQ:INTU",
    "NASDAQ:AAPL", "NASDAQ:NVDA", "NASDAQ:TSLA", "NASDAQ:MSFT", "NASDAQ:GOOGL",
    "NASDAQ:AMZN", "NASDAQ:META", "NASDAQ:AMD", "NASDAQ:INTC", "NASDAQ:NFLX",
    "NASDAQ:ADBE", "NASDAQ:CSCO", "NASDAQ:CMCSA", "NASDAQ:PEP", "NASDAQ:COST",
    "NASDAQ:AVGO", "NASDAQ:TXN", "NASDAQ:QCOM", "NASDAQ:AMAT", "NASDAQ:INTU",
]


async def main():
    await wait_for_cdp(timeout=10)
    async with TV(port=9222) as tv:
        print("Starting batch scan of 100 symbols ...", flush=True)
        t0 = asyncio.get_running_loop().time()
        results = await tv.batch(SYMBOLS, ["D"], action="ohlcv")
        elapsed = asyncio.get_running_loop().time() - t0
        unique = len(results)
        success = sum(1 for v in results.values() if v.get("D") is not None)
        failed = sum(1 for v in results.values() if v.get("D") is None)
        total_calls = len(SYMBOLS)
        print(f"\nResults: {success} unique succeeded, {failed} unique failed, "
              f"out of {total_calls} total calls ({elapsed:.0f}s)")
        for sym, tfs in list(results.items())[:5]:
            d = tfs.get("D")
            print(f"  {sym}: close={d.get('close', '?'):>10}" if d else f"  {sym}: ---- FAILED ----")


if __name__ == "__main__":
    asyncio.run(main())
