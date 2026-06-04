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

## Deployment: automation server + manual workstation

Two separate Chrome instances, same TV account, no conflicts:

| Role | Where | Purpose |
|------|-------|---------|
| **Automation server** | Docker on Oracle ARM | Headless Chrome + pytvtools scripts running 24/7 |
| **Workstation** | Your laptop | Visible Chrome for manual charting, drawing, indicator setup |

**Pytvtools connects to either** — it just needs a CDP port. The automation server drives the headless instance. You draw on your laptop's TV window independently.

```
┌──────────────────────────┐     ┌──────────────────────────┐
│  Oracle ARM (Docker)     │     │  Your laptop             │
│  Chrome headless :9222   │     │  Chrome (visible)        │
│  pytvtools scripts       │     │  Manual charting         │
│  ┌────────────────┐      │     │  Drawings, indicators    │
│  │ TV(port=9222)  │      │     └──────────────────────────┘
│  └────────────────┘      │
└──────────────────────────┘
```

Headless and visible Chrome logged into the same TV account work fine — they share the same layouts and settings server-side. Draw on your laptop, pytvtools reads those drawings from the headless instance via `get_pine_lines()` / `get_pine_labels()`.

For one-off debugging from your laptop against the server's Chrome:
```bash
ssh -L 9222:localhost:9222 user@oracle-instance
# Then connect chrome://inspect or run pytvtools locally
```

## Docker (ARM64 / x86_64)

```bash
docker compose -f docker/docker-compose.yml build
docker compose -f docker/docker-compose.yml up -d
docker compose exec pytvtools python examples/basic.py
```

The container starts Chrome headless with CDP on port 9222. Source code is volume-mounted — edits on the host take effect immediately. Same image runs on your laptop and Oracle ARM.

The entrypoint starts Chrome in the background and waits for CDP, then runs the provided CMD. The `-d` flag runs it detached; use `docker compose exec` to run scripts.

## Disclaimer

Not affiliated with TradingView Inc. Uses Chrome DevTools Protocol — a standard debugging interface in all Chromium-based applications. Using it to automate TradingView may conflict with TradingView's Terms of Service. Not financial advice.
