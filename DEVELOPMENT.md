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

The package is installed in editable mode at `/app`. Inside the container,
no reinstall is needed after source edits.

## Running commands

All commands run **in the container**, never on the host:

```bash
# Tests
docker exec docker-pytvtools-1 python -m pytest tests/ -m "not integration" -v
docker exec docker-pytvtools-1 python -m pytest tests/ -m integration -v --capture=no

# Run an example
docker exec docker-pytvtools-1 python examples/basic.py

# Unit test count: 122 (all mock, no Chrome needed)
# Integration test count: 8 (requires live Chrome + TV tab)
```

## Architecture

```
Host edits → src/pytvtools/*.py → mounted to /app → runs in container
```

| File | Purpose |
|------|---------|
| `src/pytvtools/tv.py` | `TV` — all high-level methods (CDP-based) |
| `src/pytvtools/tvdata.py` | `TVData` — direct WebSocket OHLCV fetcher (no CDP) |
| `src/pytvtools/cdp.py` | `CdpConnection` — WebSocket transport, `Runtime.evaluate` |
| `src/pytvtools/chrome.py` | `Chrome` — launch/stop/restart headless Chrome |
| `src/pytvtools/collector.py` | `Collector` — multi-symbol batch data collection + parquet export |
| `src/pytvtools/mcp_server.py` | MCP server wrapping all TV methods |
| `src/pytvtools/__init__.py` | Public exports |
| `src/pytvtools/watchlists.py` | `Watchlist` — frozen dataclass + predefined watchlists |
| `tests/test_tv.py` | Unit tests for TV methods |
| `tests/test_tvdata.py` | Unit tests for TVData direct WS fetcher |
| `tests/test_cdp.py` | Unit tests for CDP transport |
| `tests/test_chrome.py` | Unit tests for Chrome lifecycle |
| `examples/` | Runnable examples (also integration test targets) |

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
