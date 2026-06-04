# pytvtools — Agent Guide

Pure Python CDP library for TradingView in Chrome. No Node.js, no submodules.

## Key modules

| File | What |
|------|------|
| `src/pytvtools/cdp.py` | `CdpConnection` — WebSocket transport for CDP `Runtime.evaluate` |
| `src/pytvtools/chrome.py` | `Chrome` — launch/stop/restart headless Chrome with CDP |
| `src/pytvtools/tv.py` | `TV` — high-level TradingView client (main interface) |
| `src/pytvtools/__init__.py` | Re-exports |

## Usage

```python
from pytvtools import TV, Chrome, wait_for_cdp

# Option A: external Chrome
await wait_for_cdp()
async with TV() as tv:
    await tv.set_symbol("BTCUSD")
    data = await tv.get_ohlcv(summary=True)

# Option B: managed Chrome
chrome = Chrome()
await chrome.start(headless=True)
async with TV() as tv:
    rsi = await tv.get_study_values()
await chrome.stop()
```

## All TV methods

- `get_state()` → `{symbol, timeframe, chartType}`
- `set_symbol(symbol: str)`
- `set_timeframe(tf: str)` — "D", "60", "15", etc.
- `set_chart_type(t: int | str)` — Candles=1, Line=2, etc.
- `scroll_to_date(date: str)` — "2025-01-15" or unix ts
- `get_visible_range()` → `{from, to}`
- `get_ohlcv(count=500, summary=False)` → bars or stats
- `get_quote(symbol=None)` → real-time price
- `get_study_values()` → `{indicator_name: values}`
- `add_indicator(name, inputs=None)` — full name like "Relative Strength Index"
- `remove_indicator(entity_id)`
- `capture_screenshot()` → base64 PNG
- `get_pine_lines(study_filter=None)` → price levels
- `get_pine_labels(study_filter=None, max_labels=50)` → text labels
- `batch(symbols, timeframes, action)` — multi-symbol scan
- `pine_set_source(source)` — inject Pine code
- `pine_compile()` — compile and read errors

## MCP server (optional)

```bash
# pip install pytvtools[mcp]
# then run: pytvtools-mcp
```

Registers all TV methods as MCP tools. Agent calls them like any other tool.

## Chrome launch

Cross-platform — works in both bash and PowerShell:
```bash
pytvtools-chrome
```

Or from Python:
```python
from pytvtools import Chrome
chrome = Chrome()
await chrome.start(headless=True)
```

## Remote tunnel

```bash
ssh -L 9222:localhost:9222 user@oracle-arm-instance
```
