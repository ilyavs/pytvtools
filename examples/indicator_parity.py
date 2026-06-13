"""Verify that Python indicator calculations match TradingView's.

Demonstrates the full parity-check workflow:
1. Fetch OHLCV bars
2. Compute RSI in Python
3. Add the same indicator on TradingView
4. Read TV's values via get_indicator_data
5. Compare by timestamp and report differences

Usage:
    docker exec -w /app docker-pytvtools-1 python examples/indicator_parity.py
"""

import asyncio
import logging

from pytvtools import TV, wait_for_cdp
from pytvtools.indicator_parity import compare_indicator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

SYMBOL = "BINANCE:BTCUSDT"
TIMEFRAME = "1D"
MAX_BARS = 500


async def main() -> None:
    await wait_for_cdp()

    async with TV() as tv:
        await tv.set_symbol(SYMBOL)
        await tv.set_timeframe(TIMEFRAME)

        # --- RSI ---
        print("=" * 60)
        print("Verifying RSI (14) ...")
        report = await compare_indicator(
            tv, SYMBOL, TIMEFRAME, "STD;RSI",
            max_bars=MAX_BARS, tolerance=0.01,
        )
        print(report.summary())
        if report.mismatches:
            print("First 5 mismatches:")
            for m in report.mismatches[:5]:
                print(f"  ts={m.timestamp}  py={m.py_val:.4f}  tv={m.tv_val:.4f}  delta={m.delta:.6f}")
        else:
            print("  All values match within tolerance!")
        print()

        # Rinse — remove the indicator TV added
        await tv.remove_all_indicators()

        # --- SMA ---
        print("=" * 60)
        print("Verifying SMA (20) ...")
        report = await compare_indicator(
            tv, SYMBOL, TIMEFRAME, "STD;SMA",
            max_bars=MAX_BARS, tolerance=0.01,
        )
        print(report.summary())
        if report.mismatches:
            print("First 5 mismatches:")
            for m in report.mismatches[:5]:
                print(f"  ts={m.timestamp}  py={m.py_val:.4f}  tv={m.tv_val:.4f}  delta={m.delta:.6f}")
        else:
            print("  All values match within tolerance!")
        print()

        await tv.remove_all_indicators()

        # --- EMA ---
        print("=" * 60)
        print("Verifying EMA (20) ...")
        report = await compare_indicator(
            tv, SYMBOL, TIMEFRAME, "STD;EMA",
            max_bars=MAX_BARS, tolerance=0.01,
        )
        print(report.summary())
        if report.mismatches:
            print("First 5 mismatches:")
            for m in report.mismatches[:5]:
                print(f"  ts={m.timestamp}  py={m.py_val:.4f}  tv={m.tv_val:.4f}  delta={m.delta:.6f}")
        else:
            print("  All values match within tolerance!")
        print()

        await tv.remove_all_indicators()

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
