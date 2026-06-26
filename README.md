# pytvtools

Pure Python CDP library for TradingView in Chrome — no Node.js.

Talk to TradingView's chart widget via Chrome DevTools Protocol. Read price data, add and read indicator values, run multi-symbol scans, inject Pine Script, and more.

## Install

```bash
# Lite — TVData (direct WebSocket OHLCV) + Python indicators only, no Chrome/CDP needed
pip install pytvtools

# Full — adds CDP (TV class, screenshots, indicators, bar replay, etc.) + parquet export
pip install pytvtools[full]

# MCP server (host-side, connects to Chrome at localhost:9222)
pip install pytvtools[mcp]
```

## Quick start

**Managed Chrome (start/stop from Python):**
```python
import asyncio
from pytvtools import Chrome, TV

async def main():
    chrome = Chrome()
    await chrome.start(headless=True)
    async with TV() as tv:
        state = await tv.get_state()
        print(state)
    await chrome.stop()

asyncio.run(main())
```

**Or connect to an already-running Chrome** (launched with `--remote-debugging-port=9222`):
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

**Prerequisite:** Chrome with `https://www.tradingview.com/chart/` open. The auto-start path handles this.

## API

### Authentication

| Method | Returns | Description |
|--------|---------|-------------|
| `is_logged_in()` | `bool` | Check if currently logged in to a TradingView account |
| `login(username=None, password=None, timeout=120)` | `dict` | Log in — programmatic (pass creds) or manual (omit creds, opens sign-in page for you) |
| `logout(timeout=10)` | `dict` | Sign out via the user avatar menu |

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
| `get_indicator_data(entity_id)` | `dict` | All historical plot values per plot name |
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
| `list_templates(tab=None)` | `list[{name, description}]` | List saved templates (tab: `"my templates"`, `"technicals"`, `"financials"`) |
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

### Bar replay

| Method | Returns | Description |
|--------|---------|-------------|
| `replay_start(date=None)` | `dict` | Enter bar-replay mode, optionally at a specific date |
| `replay_stop()` | `dict` | Exit replay mode, return to realtime |
| `replay_status()` | `dict` | Current replay state (date, autoplay, etc.) |
| `replay_step()` | `dict` | Advance one bar |
| `replay_autoplay(speed=0)` | `dict` | Toggle autoplay, optionally set delay (ms) |

### Multi-symbol

| Method | Returns | Description |
|--------|---------|-------------|
| `batch(symbols, timeframes, action)` | `{symbol: {tf: data}}` | CDP-based multi-symbol scan |
| `get_ohlcv_multi(symbols, interval, ...)` | `{symbol: data}` | Parallel WS fetch — no Chrome needed |

## Examples

```
examples/
  basic.py                      — connect, state, OHLCV, study values
  chart_control.py              — symbol, timeframe, chart type, scroll, screenshot
  add_indicator_read_values.py  — add indicators, read values, change inputs
  multi_symbol_scan.py          — batch() scan across symbols/timeframes
  search_and_add_indicator.py   — search by keyword, add by study_id
  indicator_templates.py        — list and apply indicator templates
  get_indicator_data.py         — all historical plot values for an indicator
  pine_interaction.py           — inject Pine Script, compile, read drawings
  tvdata_ohlcv.py               — fast OHLCV via direct WebSocket (no Chrome)
  collector_demo.py             — Collector: multi-symbol batch + parquet/JSON export
  indicator_parity.py           — compare Python indicator values vs TradingView
  tvdata_multi.py               — parallel OHLCV fetch across 25 symbols (no Chrome)
```

```bash
# With Docker:
docker exec docker-pytvtools-1 python examples/basic.py

# Without Docker (Chrome must be running with CDP):
python examples/basic.py
```

All examples operate on the **existing** chart tab — no tab creation.

## Tests

```bash
# Unit tests need [dev] + [full] (for httpx/pyarrow in mocked CDP tests)
pip install "pytvtools[full,dev]"
```

```bash
# Unit tests — no Chrome needed (all mocks)
pytest tests/ -m "not integration" -v

# Integration tests — requires live Chrome + TV tab
pytest tests/ -m integration -v --capture=no
```

186 unit tests mock everything. 12 integration tests run every example against real TV.

## TradingView JS API reference

The full internal API map (public chart API vs widget internals, study ID formats, plot value access, glitch avoidance) is in [`CLAUDE.md`](CLAUDE.md). Key points:

- Use `window.TradingViewApi.chart()` — the public API, avoids the "temporary glitch" screen
- Add indicators via `chart()._createStudy({type: "pine", pineId: "STD;RSI"})` for built-ins, `{type: "java", studyId: "Name@tv-basicstudies"}` for java-type built-ins
- Read plot values via `model.dataSourceForId(id)._data._items`
- Study ID formats: `STD;Name` (pine) or `Name@tv-basicstudies` (java) for built-ins, `PUB;id` for community

## MCP server (optional, host-side)

```
pip install pytvtools[mcp]
pytvtools-mcp
```

Exposes all TV methods as MCP tools. Runs **on the host** (not in Docker)
and connects to Chrome at `localhost:9222` (Docker port mapping).

### Credential resolution

The ``login`` MCP tool resolves credentials in this order:

1. **Named profile in config** — ``profiles.<name>.username`` / ``profiles.<name>.password``
   from ``~/.tv/config``. You **must** pass ``profile="<name>"`` to the tool —
   no root-level ``username`` fallback is supported.
2. **Environment variables** — ``TV_USERNAME`` and ``TV_PASSWORD``.
3. **Manual mode** — navigates to the sign-in page and waits for you to type.

Config file format:

```json
{
  "profiles": {
    "work": {
      "username": "work@tradingview.com",
      "password": "work_secret"
    },
    "personal": {
      "username": "personal@example.com",
      "password": "personal_secret"
    }
  }
}
```

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
docker exec docker-pytvtools-1 python examples/basic.py
```

Source code is volume-mounted at `/app`. Run `pip install -e /app` inside the container after editing for live changes.

## Design

```
Your script → pytvtools (Python)
               → CDP WebSocket → Chrome (headless)
                                   → tradingview.com/chart
```

**Dependencies:** `websockets` (core) — `httpx` + `pyarrow` for `[full]`, `mcp` for `[mcp]`.

## Why raw CDP

| pytvtools | tradingview-mcp wrapper |
|-----------|------------------------|
| `pip install` | git submodule + npm + node |
| No Node.js | Requires Node.js |
| Direct WebSocket to Chrome | stdio JSON-RPC to Node.js proxy |
| Pure Python | NPM audit, version drift |

## Disclaimer

Not affiliated with TradingView Inc. Uses Chrome DevTools Protocol — a standard debugging interface in all Chromium-based applications. Using it to automate TradingView may conflict with TradingView's Terms of Service. Not financial advice.
