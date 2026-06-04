# pytvtools

Pure Python CDP library for TradingView in Chrome — no Node.js, no MCP server dependency.

Talk directly to TradingView's chart widget via Chrome DevTools Protocol. Read data, closed-source indicator values, Pine drawings. Build custom screeners, algos, and backtesting scripts.

## Quick start

```bash
pip install pytvtools
```

**Launch Chrome and connect — works on Linux, macOS, and Windows:**
```python
import asyncio
from pytvtools import Chrome, TV

async def main():
    # Start headless Chrome (auto-detects binary, cross-platform)
    chrome = Chrome()
    await chrome.start(headless=True)

    # Connect to TradingView and read data
    async with TV() as tv:
        state = await tv.get_state()
        ohlcv = await tv.get_ohlcv(summary=True)
        studies = await tv.get_study_values()
        print(studies.get("Relative Strength Index"))

    await chrome.stop()

asyncio.run(main())
```

Or launch Chrome manually (same command works in PowerShell and bash):
```bash
pytvtools-chrome
```

## API

| Method | Description |
|--------|-------------|
| `get_state()` | Symbol, timeframe, chart type |
| `set_symbol(s)` | Change ticker |
| `set_timeframe(tf)` | Change resolution (`D`, `60`, `15`, etc.) |
| `get_ohlcv(count, summary)` | Price bars or compact stats |
| `get_study_values()` | All visible indicator values |
| `get_quote(symbol)` | Real-time quote |
| `add_indicator(name)` | Add indicator by full name |
| `get_pine_lines(study_filter)` | Horizontal price levels from Pine indicators |
| `get_pine_labels(study_filter)` | Text labels from Pine indicators |
| `capture_screenshot()` | Base64 PNG screenshot |
| `batch(symbols, timeframes)` | Multi-symbol/timeframe scan |
| `scroll_to_date(date)` | Jump to a date |
| `get_visible_range()` | Visible date range |

## Design

```
┌────────────────────────────────────────────┐
│  Your script / agent                       │
│  import pytvtools / call MCP tools         │
└──────────┬─────────────────────────────────┘
           │
┌──────────▼─────────────────────────────────┐
│  pytvtools (pure Python)                   │
│  │ CDP WebSocket ←→ Chrome                │
│  │ JS injected into TV widget             │
└──────────┬─────────────────────────────────┘
           │
┌──────────▼─────────────────────────────────┐
│  Chrome (headless) → tradingview.com/chart │
│  Your closed-source indicators applied     │
└────────────────────────────────────────────┘
```

## Dependencies

- `httpx` — CDP discovery (HTTP)
- `websockets` — CDP evaluation (WebSocket)
- `mcp` (optional) — expose as MCP server for agent use

## Why raw CDP vs wrapping tradingview-mcp

| pytvtools | tradingview-mcp wrapper |
|-----------|------------------------|
| `pip install` | git submodule + npm install + node |
| No Node.js on ARM | Requires Node.js |
| Direct WebSocket to Chrome | stdio JSON-RPC to Node.js proxy |
| 3 Python files | NPM audit, version drift |

## MCP server mode (optional)

```bash
pip install pytvtools[mcp]
pytvtools-mcp
```

Exposes all TV operations as MCP tools for Claude Code / any MCP agent.

## Docker (ARM64 / x86_64)

```bash
docker compose -f docker/docker-compose.yml build
docker compose -f docker/docker-compose.yml up -d
docker compose exec pytvtools python examples/basic.py
```

The container starts Chrome headless with CDP on port 9222. Source code is volume-mounted — edits on the host take effect immediately. Same image runs on your laptop and Oracle ARM.

The entrypoint starts Chrome in the background and waits for CDP, then runs the provided CMD. The `-d` flag runs it detached; use `docker compose exec` to run scripts.

## Remote use (Oracle ARM + SSH tunnel)

```bash
ssh -L 9222:localhost:9222 user@oracle-instance
# Then run pytvtools locally — talks to the remote Chrome
```

## Disclaimer

Not affiliated with TradingView Inc. Uses Chrome DevTools Protocol — a standard debugging interface in all Chromium-based applications. Using it to automate TradingView may conflict with TradingView's Terms of Service. Not financial advice.
