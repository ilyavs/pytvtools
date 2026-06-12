"""Fast OHLCV fetching via direct WebSocket — no CDP, no browser needed.

Shows the TVData class which connects directly to TradingView's
WebSocket protocol (bypasses Chrome entirely).

Usage:
    docker exec docker-pytvtools-1 python examples/tvdata_ohlcv.py
"""
from pytvtools import TVData


async def main():
    # Option C: Direct WebSocket (no Chrome needed, OHLCV only)
    async with TVData() as d:
        # Fetch daily bars
        bars = await d.get_ohlcv("NASDAQ:AAPL", "1D", 5)
        print("Daily bars for AAPL:")
        for b in bars:
            print(f"  {b['timestamp']}  O:{b['open']:.2f}  H:{b['high']:.2f}  L:{b['low']:.2f}  C:{b['close']:.2f}  V:{b['volume']:.0f}")

        # Summary mode
        summary = await d.get_ohlcv("BINANCE:BTCUSDT", "1D", 100, summary=True)
        print(f"\nBTC 100-day summary: high={summary['high']:.2f}  low={summary['low']:.2f}  "
              f"avg_vol={summary['avg_volume']:.0f}  range={summary['range']:.2f}")

        # Intraday
        bars_5m = await d.get_ohlcv("NASDAQ:AAPL", "5", 10)
        print(f"\nAAPL 5-minute bars: {len(bars_5m)} bars (last close: {bars_5m[-1]['close']:.2f})")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
