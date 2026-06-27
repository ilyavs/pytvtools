# Development

## Dev environment

A Docker container (`docker-pytvtools-1`) provides a consistent Linux environment.
The source tree is mounted from the host — edit on the host, run everything in the container.

**Check if it's already running:**
```bash
docker exec docker-pytvtools-1 echo ok
```

**If not running, start it:**
```bash
docker compose -f docker/docker-compose.yml up -d
```

Both packages are installed in editable mode at `/app`. Inside the container,
no reinstall is needed after source edits:

```bash
pip install -e src/pytvtools_core && pip install -e .
```

## Running commands

All commands run **in the container**, never on the host:

```bash
# Tests
docker exec -w /app docker-pytvtools-1 python -m pytest tests/ -m "not integration" -v
docker exec -w /app docker-pytvtools-1 python -m pytest tests/ -m integration -v --capture=no

# Run an example
docker exec -w /app docker-pytvtools-1 python examples/basic.py

# Unit test count: 210 (all mock, no Chrome needed)
# Integration tests: auto-discovers examples/*.py (currently 14, requires live Chrome)
```

## Architecture

Two packages in one repo:

| Package | Directory | Publishes as | Contents |
|---------|-----------|-------------|----------|
| **CDP** | `src/pytvtools/` | `pytvtools` | CDP-dependent code |
| **Core** | `src/pytvtools_core/` | `pytvtools-core` | indicators, watchlists, TVData |

The core package is standalone — can be synced to a public repo via `python scripts/sync_core.py`.

| File | Package | Purpose |
|------|---------|---------|
| `src/pytvtools/tv.py` | pytvtools | `TV` — all high-level methods (CDP-based) |
| `src/pytvtools/cdp.py` | pytvtools | `CdpConnection` — WebSocket transport, `Runtime.evaluate` |
| `src/pytvtools/chrome.py` | pytvtools | `Chrome` — launch/stop/restart headless Chrome |
| `src/pytvtools/collector.py` | pytvtools | `Collector` — multi-symbol batch (CDP-based, studies too); `TVDataCollector` — OHLCV-only batch |
| `src/pytvtools/indicator_parity.py` | pytvtools | `compare_indicator()` — Python vs TV indicator comparison |
| `src/pytvtools/pine_parity.py` | pytvtools | Pine Script parity checks |
| `src/pytvtools/mcp_server.py` | pytvtools | MCP server wrapping all TV methods |
| `src/pytvtools/__init__.py` | pytvtools | Public exports |
| `src/pytvtools_core/indicators.py` | pytvtools-core | Pure-Python SMA, EMA, RSI, MACD implementations |
| `src/pytvtools_core/watchlists.py` | pytvtools-core | `Watchlist` — frozen dataclass + predefined watchlists |
| `src/pytvtools_core/tvdata.py` | pytvtools-core | `TVData` — direct WebSocket OHLCV fetcher (no CDP) |
| `tests/test_tv.py` | both | Unit tests for TV methods |
| `tests/test_tvdata.py` | pytvtools-core | Unit tests for TVData direct WS fetcher |
| `tests/test_cdp.py` | pytvtools | Unit tests for CDP transport |
| `tests/test_chrome.py` | pytvtools | Unit tests for Chrome lifecycle |
| `tests/test_indicators.py` | pytvtools-core | Unit tests for Python indicators |
| `tests/test_indicator_parity.py` | pytvtools | Unit tests for comparison utility |
| `tests/test_pine_parity.py` | pytvtools | Unit tests for Pine parity |
| `tests/test_collector.py` | pytvtools | Unit tests for Collector (CDP-based) |
| `tests/test_tvdata_collector.py` | pytvtools | Unit tests for TVDataCollector |
| `tests/test_watchlists.py` | pytvtools-core | Unit tests for Watchlist |
| `tests/test_integration.py` | pytvtools | Runs all examples as integration tests |
| `examples/` | both | Runnable examples (also integration test targets) |

## Implementation rules

1. **Every feature must work via CDP only** — `Runtime.evaluate` in the TV chart
   tab. No direct TradingView REST API calls, no HTTP endpoints.
2. **Use the public chart API** — `window.TradingViewApi.chart()` — to avoid the
   "temporary glitch" overlay that appears when using the internal widget getter.
3. **Study ID formats:**
   - Built-in (pine): `STD;Name` (e.g. `STD;RSI`, `STD;SMA`) — use `type: "pine"`
   - Built-in (java): `Name@tv-basicstudies` (e.g. `Volume@tv-basicstudies`) — use `type: "java"`
   - Community: `PUB;id` (e.g. `PUB;85`) — use `type: "pine"`
   - `search_indicators` returns the correct `study_id` for use with `add_indicator`
4. **JS patterns:**
   - `self._eval(js_string)` — runs JS, returns result
   - `self._eval(js_string, await_promise=True)` — for async/Promise-returning JS
   - `_js_str(s)` — safe string interpolation into JS
   - `_chart_call(method, *args)` — calls a method on `window.TradingViewApi.chart()`
5. **Indicator limit** — default 2, configurable via `TV_MAX_INDICATORS` env var.
   `TooManyIndicatorsError` is raised when exceeded.
6. **All TV methods listed in `tv.py` must also be registered in `mcp_server.py`**.

## What to do on a fresh session

1. Check the container is running (`docker exec docker-pytvtools-1 echo ok`)
2. Start it if needed (`docker compose -f docker/docker-compose.yml up -d`)
3. Read `CLAUDE.md` for the full TradingView JS API reference (chart API internals,
   study data access patterns, glitch avoidance)
4. Read `tv.py` to understand existing patterns before adding new methods
5. Run unit tests to confirm baseline
6. Implement, test, verify all tests still pass

## Periodic Volume Profile Parity

The custom Pine implementation at `pine_indicators/pvp.pine` achieves **100% match
on completed period POCs** against TradingView's built-in Periodic Volume Profile
(Total volume mode, 24 rows, 1D period on 60m chart).

Key findings:

| Aspect | Detail |
|--------|--------|
| **Completed POC match** | 25/25 period-end bars match at ±0.01 tolerance |
| **Developing POC gap** | ~12% mismatch — mid-period values differ due to data pipeline timing, not algorithm |
| **Lower TF requirement** | `request.security_lower_tf(syminfo.tickerid, "10", [high, low, volume])` — matches TV's built-in behavior for 60m charts |
| **Pine v6 workaround** | `array.concat()` instead of `for`-loop + `array.push()` — `push()` silently fails with `security_lower_tf` arrays |
| **POC formula** | `pls_min + (poc_row + 0.5) * tick_size` — center of the highest-volume row |
| **Volume distribution** | `vol_per_tick = volume / num_ticks` — equal volume per tick, matching built-in |

### Running parity comparison

```python
from pytvtools import TV, wait_for_cdp
from pytvtools.indicator_parity import compare_pvp

async with TV() as tv:
    result = await compare_pvp(tv, "BATS:INTC", "60")
    print(f"Match: {result['matched']}/{result['total']} ({result['match_rate']:.1f}%)")
```

The function adds both the built-in PVP and the custom Pine version, waits for
data, and compares only on timestamps where both have values (completed-period
POC bars at 19:00 ET).
