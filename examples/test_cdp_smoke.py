"""Quick CDP smoke test — check if eval works on the live TV tab."""
import asyncio
import logging
logging.basicConfig(level=logging.INFO)
from pytvtools import TV, wait_for_cdp


async def main():
    await wait_for_cdp(timeout=10)
    async with TV(port=9222) as tv:
        print("Connected to TV tab")
        try:
            sym = await asyncio.wait_for(tv._eval("(window.TradingViewApi ? window.TradingViewApi.chart().symbol() : null)"), timeout=5)
            print(f"Current symbol: {sym}")
        except asyncio.TimeoutError:
            print("TIMEOUT: _eval hung for 5s")
        except Exception as e:
            print(f"ERROR: {e}")

        try:
            state = await asyncio.wait_for(tv.get_state(), timeout=5)
            print(f"State: {state}")
        except asyncio.TimeoutError:
            print("TIMEOUT: get_state hung for 5s")
        except Exception as e:
            print(f"ERROR: {e}")


if __name__ == "__main__":
    asyncio.run(main())
