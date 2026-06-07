# pytvtools

Pure Python CDP library for TradingView in Chrome — no Node.js.

Talk to TradingView's chart widget via Chrome DevTools Protocol. Read price data, add and read indicator values, run multi-symbol scans.

## Quick start

```
pip install pytvtools
```

**Managed Chrome (start/stop from Python):**
```python
import asyncio
from pytvtools import Chrome, TV

async def main():
    chrome = Chrome()
    await chrome.start(headless=True)
    async with TV() as tv:
        state = await tv.get_state()
        print(state)  # {symbol: ..., timeframe: ..., chartType: ...}
    await chrome.stop()

asyncio.run(main())
```

**Or connect to an already-running Chrome** (launched with `--remote-debugging-port=9222`, TV chart tab open):
```python
from pytvtools import TV, wait_for_cdp

await wait_for_cdp(timeout=10)
async with TV() as tv:
    print(await tv.get_state())
```

**Print the Chrome launch command** for your platform (bash and PowerShell):
```
pytvtools-chrome
```
This prints the command — copy-paste it to launch Chrome.

**Prerequisite:** Chrome with `https://www.tradingview.com/chart/` open. The auto-start path handles this.

## API

### Chart control

| Method | Returns | Description |
|--------|---------|-------------|
| `get_state()` | `{symbol, timeframe, chartType}` | Current symbol, timeframe, chart type |
| `set_symbol(symbol)` | — | Change ticker |
| `set_timeframe(tf)` | — | Change resolution (`D`, `60`, `15`, `5`, `1`, `W`, `M`) |
| `set_chart_type(t)` | — | Candles=1, Line=2, Area=3 |
| `scroll_to_date(date)` | — | Jump to a date (`"2025-01-15"`) |
| `get_visible_range()` | `{from, to}` | Visible date range (unix timestamps) |

### Data

| Method | Returns | Description |
|--------|---------|-------------|
| `get_ohlcv(count=500, summary=False)` | `list[bar]` or dict | Price bars or compact stats |
| `get_study_values()` | `{name: {title, values}}` | All visible indicator plot values |
| `get_quote()` | `{symbol: str}` | Current symbol |
| `capture_screenshot()` | `str` | Base64 PNG |

### Indicators

| Method | Returns | Description |
|--------|---------|-------------|
| `search_indicators(query)` | `list[{id, name, study_id}]` | Search by keyword — includes built-in + community |
| `add_indicator(indicator, inputs=None)` | `str \| None` | Add by study ID or display name |
| `remove_indicator(entity_id)` | — | Remove by entity ID |
| `remove_all_indicators()` | — | Remove all studies |
| `set_indicator_inputs(entity_id, inputs)` | — | Change input values on an existing indicator |
| `get_indicator_count()` | `int` | Number of indicators currently on the chart |
| `list_templates(tab=None)` | `list[{name, description}]` | List saved templates (tab: ``"my templates"``, ``"technicals"``, ``"financials"``) |
| `apply_template(name)` | — | Apply a saved indicator template (searches all tabs) |

### Pine Script drawings

| Method | Returns | Description |
|--------|---------|-------------|
| `get_pine_lines(study_filter=None)` | `list[{id, price, text}]` | Horizontal price levels from Pine indicators |
| `get_pine_labels(study_filter=None, max_labels=50)` | `list[{text, price, time}]` | Text labels from Pine indicators |

### Pine Script editor

| Method | Returns | Description |
|--------|---------|-------------|
| `pine_set_source(source)` | — | Inject source into the Pine editor |
| `pine_compile()` | `{errors}` | Compile and return errors |

### Multi-symbol

| Method | Returns | Description |
|--------|---------|-------------|
| `batch(symbols, timeframes, action)` | `{symbol: {tf: data}}` | Scan multiple symbols/timeframes |

## Examples

```
examples/
  basic.py                      — connect, state, OHLCV, study values
  chart_control.py              — symbol, timeframe, chart type, scroll, visible range
  add_indicator_read_values.py  — add RSI, read values, remove
  multi_symbol_scan.py          — iterate symbols, read indicators
  pine_interaction.py           — inject Pine Script, compile, read errors
  search_and_add_indicator.py   — search built-in & community, add by study_id
  indicator_templates.py        — list templates from any tab, apply by name
```

```bash
# With Docker:
docker compose exec pytvtools python examples/basic.py

# Without Docker (Chrome must be running):
python examples/basic.py
```

All examples operate on the **existing** chart tab — no tab creation.

## Tests

```
pip install pytvtools[dev]
```

```bash
# Unit tests — no Chrome needed (all mocks)
pytest tests/ -m "not integration" -v

# Integration tests — requires live Chrome + TV tab
pytest tests/ -m integration -v --capture=no
```

106 unit tests mock everything. 6 integration tests run every example against real TV.

## TradingView JS API reference

The full internal API map (public chart API vs widget internals, study ID formats, plot value access, glitch avoidance) is in [`CLAUDE.md`](CLAUDE.md). Key points:

- Use `window.TradingViewApi.chart()` — the public API, avoids the "temporary glitch" screen
- Add indicators via `chart()._createStudy({type: "java", studyId: "Name@tv-basicstudies"})`
- Read plot values via `model.dataSourceForId(id)._data._items`
- Study ID format: `Name@tv-basicstudies` for built-ins, raw ID for custom

## MCP server (optional)

```
pip install pytvtools[mcp]
pytvtools-mcp
```

Exposes all TV methods as MCP tools.

## Deployment

Two separate Chrome instances, same TV account:

| Role | Where | Purpose |
|------|-------|---------|
| **Automation server** | Docker or remote VM | Headless Chrome + pytvtools scripts |
| **Workstation** | Your laptop | Visible Chrome for manual charting |

```
┌──────────────────────┐     ┌──────────────────────┐
│  Server (Docker/VM)  │     │  Your laptop         │
│  Chrome headless     │     │  Chrome (visible)    │
│  pytvtools scripts   │     │  Manual charting     │
└──────────────────────┘     └──────────────────────┘
```

Remote debugging:
```
ssh -L 9222:localhost:9222 user@your-server
```

## Docker

```bash
docker compose -f docker/docker-compose.yml build
docker compose -f docker/docker-compose.yml up -d
docker compose exec pytvtools python examples/basic.py
```

Source code is volume-mounted at `/app`. Run `pip install -e /app` inside the container after editing for live changes.

## Design

```
Your script → pytvtools (3 core Python files)
               → CDP WebSocket → Chrome (headless)
                                  → tradingview.com/chart
```

**Dependencies:** `httpx` (HTTP), `websockets` (CDP), `mcp` (optional).

## Why raw CDP

| pytvtools | tradingview-mcp wrapper |
|-----------|------------------------|
| `pip install` | git submodule + npm + node |
| No Node.js | Requires Node.js |
| Direct WebSocket to Chrome | stdio JSON-RPC to Node.js proxy |
| 3 Python files | NPM audit, version drift |

## Disclaimer

Not affiliated with TradingView Inc. Uses Chrome DevTools Protocol — a standard debugging interface in all Chromium-based applications. Using it to automate TradingView may conflict with TradingView's Terms of Service. Not financial advice.
