# pytvtools

Pure Python CDP library for TradingView in Chrome — no Node.js, no MCP server dependency.

Talk directly to TradingView's chart widget via Chrome DevTools Protocol. Read price data, add and read indicator values, run multi-symbol scans. Build custom screeners, algos, and backtesting scripts.

## Quick start

```bash
pip install pytvtools
```

**Launch Chrome and connect — works on Linux, macOS, and Windows:**
```python
import asyncio
from pytvtools import Chrome, TV

async def main():
    chrome = Chrome()
    await chrome.start(headless=True)

    async with TV() as tv:
        state = await tv.get_state()
        ohlcv = await tv.get_ohlcv(summary=True)

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
| `set_chart_type(t)` | Candles=1, Line=2, Area=3 |
| `get_ohlcv(count, summary)` | Price bars or compact stats |
| `get_study_values()` | All visible indicator values `{name: {title, values}}` |
| `get_quote()` | Current symbol quote |
| `add_indicator(study_id)` | Add by study ID (e.g. `"RSI@tv-basicstudies"`), returns entity ID |
| `remove_indicator(entity_id)` | Remove by entity ID |
| `capture_screenshot()` | Base64 PNG screenshot |
| `batch(symbols, timeframes)` | Multi-symbol/timeframe scan |
| `scroll_to_date(date)` | Jump to a date |
| `get_visible_range()` | Visible date range |
| `get_pine_lines(study_filter)` | Horizontal price levels from Pine indicators |
| `get_pine_labels(study_filter)` | Text labels from Pine indicators |

## Examples

All in `examples/` — runnable end-to-end integration tests:

```bash
docker compose exec pytvtools python examples/basic.py
docker compose exec pytvtools python examples/add_indicator_read_values.py
docker compose exec pytvtools python examples/multi_symbol_scan.py
```

All examples operate on the **existing** chart tab — no tab creation.

## Tests

```bash
# Unit tests — no Chrome needed (all mocks)
docker compose exec pytvtools python -m pytest tests/ -v

# Integration tests — requires live Chrome + TV tab
docker compose exec pytvtools python -m pytest tests/ -m integration -v --capture=no
```

83 unit tests (mock everything), 3 integration tests (run every example against real TV).

## Design

```
┌────────────────────────────────────────────┐
│  Your script / agent                       │
│  import pytvtools / call MCP tools         │
└──────────┬─────────────────────────────────┘
           │
┌──────────▼─────────────────────────────────┐
│  pytvtools (pure Python, 3 files)          │
│  │ CDP WebSocket ←→ Chrome                │
│  │ JS injected into TV widget             │
└──────────┬─────────────────────────────────┘
           │
┌──────────▼─────────────────────────────────┐
│  Chrome (headless) → tradingview.com/chart │
│  Your indicators applied, data read        │
└────────────────────────────────────────────┘
```

## TradingView JS API (discovered)

Key findings persisted in `CLAUDE.md`. Public API (`window.TradingViewApi.chart()`) avoids the "temporary glitch" screen. Add indicators via `chart()._createStudy({type: "java", studyId: "Name@tv-basicstudies"})`. Read plot values via `model.dataSourceForId(id)._data._items`.

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
| **Automation server** | Docker or remote VM | Headless Chrome + pytvtools scripts running 24/7 |
| **Workstation** | Your laptop | Visible Chrome for manual charting, drawing, indicator setup |

Pytvtools connects to either — it just needs a CDP port.

```
┌──────────────────────────┐     ┌──────────────────────────┐
│  Server (Docker/VM)      │     │  Your laptop             │
│  Chrome headless :9222   │     │  Chrome (visible)        │
│  pytvtools scripts       │     │  Manual charting         │
│  ┌────────────────┐      │     │  Drawings, indicators    │
│  │ TV(port=9222)  │      │     └──────────────────────────┘
│  └────────────────┘      │
└──────────────────────────┘
```

For remote debugging:
```bash
ssh -L 9222:localhost:9222 user@your-server
# Then connect chrome://inspect or run pytvtools locally
```

## Docker

```bash
docker compose -f docker/docker-compose.yml build
docker compose -f docker/docker-compose.yml up -d
docker compose exec pytvtools python examples/basic.py
```

The container starts Chrome headless with CDP on port 9222. Source code is volume-mounted — edits on the host take effect immediately.

## Disclaimer

Not affiliated with TradingView Inc. Uses Chrome DevTools Protocol — a standard debugging interface in all Chromium-based applications. Using it to automate TradingView may conflict with TradingView's Terms of Service. Not financial advice.
