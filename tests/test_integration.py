"""Integration tests: run each example script against a live TradingView tab.

Requires a running Chrome with CDP on port 9222 and a TV chart tab open.
Skip with:  pytest -m "not integration"
Run with:   pytest -m integration

Cache integration tests need a working TradingView WebSocket connection
but no browser — they fetch OHLCV directly via TVData.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from pytvtools_core.cache import MarketDataCache

EXAMPLES = sorted(Path(__file__).resolve().parents[1].glob("examples/*.py"))


@pytest.mark.integration
@pytest.mark.parametrize("script", EXAMPLES, ids=lambda p: p.stem)
def test_example_runs_successfully(script: Path):
    """Each example script must exit with code 0."""
    # Ensure a clean slate for indicator-adding examples
    import asyncio
    from pytvtools import TV
    async def _clean():
        async with TV() as tv:
            await tv.remove_all_indicators()
    try:
        asyncio.run(_clean())
    except Exception as e:
        print(f"Cleanup failed, continuing: {e}")

    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        msg = (
            f"{script.name} failed (exit {result.returncode})\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
        raise AssertionError(msg)


# ---------------------------------------------------------------------------
#  Cache integration (real TVData WebSocket)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCacheIntegration:
    """Fetch real OHLCV data from TradingView and verify the cache round-trip."""

    @pytest.fixture
    def cache(self, tmp_path: Path) -> MarketDataCache:
        return MarketDataCache(mode="local", cache_dir=str(tmp_path / "cache"))

    async def test_refresh_realtime(self, cache: MarketDataCache):
        """Fetch AAPL daily bars and verify they're stored."""
        r = await cache.refresh("NASDAQ:AAPL", "1D", bars_count=100)
        assert r["fetched"] >= 50, f"Expected >=50 bars, got {r['fetched']}"
        assert r["inserted"] >= 50, f"Expected >=50 inserted, got {r['inserted']}"

        bars = cache.query("NASDAQ:AAPL", "1D")
        assert len(bars) >= 50
        assert bars[0]["timestamp"] < bars[-1]["timestamp"]  # chronological

    async def test_incremental_no_duplicates(self, cache: MarketDataCache):
        """Second refresh should add 0 new bars."""
        await cache.refresh("NASDAQ:AAPL", "1D", bars_count=100)
        r = await cache.refresh("NASDAQ:AAPL", "1D", bars_count=100)
        assert r["inserted"] == 0

    async def test_multi_symbol(self, cache: MarketDataCache):
        """Refresh multiple symbols and timeframes."""
        result = await cache.refresh_multi(
            ["NASDAQ:AAPL", "BINANCE:BTCUSDT"],
            ["1D", "60"],
            bars_count=50,
            max_concurrent=2,
        )
        for sym in ("NASDAQ:AAPL", "BINANCE:BTCUSDT"):
            for tf in ("1D", "60"):
                assert sym in result, f"Missing {sym}"
                assert tf in result[sym], f"Missing {sym}/{tf}"
                assert result[sym][tf]["fetched"] >= 20

    async def test_latest_timestamps(self, cache: MarketDataCache):
        """After refresh, latest_timestamps returns correct timestamps."""
        await cache.refresh("NASDAQ:AAPL", "1D", bars_count=100)
        rows = cache.latest_timestamps(["NASDAQ:AAPL"], ["1D"])
        assert len(rows) == 1
        assert rows[0]["latest"] is not None

    async def test_query_with_filters(self, cache: MarketDataCache):
        """Query with since/until works on real data."""
        await cache.refresh("NASDAQ:AAPL", "1D", bars_count=500)
        rows = cache.query("NASDAQ:AAPL", "1D")
        mid = rows[len(rows) // 2]["timestamp"]
        filtered = cache.query("NASDAQ:AAPL", "1D", since=mid)
        assert len(filtered) < len(rows)
        assert filtered[0]["timestamp"] == mid
