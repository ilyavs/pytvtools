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
- `get_study_values()` → `{indicator_name: {title, values: [{timestamp, value}]}}`
- `add_indicator(study_id)` — e.g. `"RSI@tv-basicstudies"`, returns entity ID
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

## TradingView JS API reference (CDP context)

All calls via `Runtime.evaluate` in the TV chart tab.

### Public chart API (preferred — won't trigger "temporary glitch" screen)

```javascript
window.TradingViewApi.chart()  // the public chart API object
```

Methods on `chart()`:
- `getState()` — `{symbol, timeframe, chartType}`
- `setSymbol(symbol)`, `setResolution(tf)`, `setChartType(type)`
- `getAllStudies()` → `[{id, name}]` (sparse entity)
- `getStudyById(id)` → study with `getInputsInfo()`, `getInputValues()`, `getStyleInfo()`, `title()`
- `getSeries(id)` → series with `barsCount()`, `data()`, `symbolSource()`
- `removeEntity(id)`, `removeAllStudies()`
- `chartWidget()` → raw widget
  - `chartWidget().model()` → chart model with `dataSources()`, `dataSourceForId(id)`, `panes()`, `createStudyInserter()`, `removeSource()`
- `_createStudy({type: "java", studyId: "Name@tv-basicstudies"})` — returns Promise<string> with entity ID

### Adding indicators

```javascript
// Correct — uses _createStudy to bypass metadata lookup
var eid = await chart()._createStudy({type: "java", studyId: "RSI@tv-basicstudies"});
// eid is the entity ID string e.g. "2tMAgd"
```

Study ID format: `Name@tv-basicstudies` for built-ins (RSI, MACD, etc.),
raw ID string for custom indicators (e.g. `SFFMev`).

### Reading indicator values

```javascript
var ds = chart().chartWidget().model().dataSourceForId(entityId);
var items = ds._data._items;  // array of {index, value: [timestamp, plotValue]}
var lastValue = items[items.length - 1].value[1];  // latest plot value
```

Key internal properties on the data source:
- `ds._data._items` — all plot values `[{index, value: [ts, val]}]`
- `ds._study` — internal study object (access with caution)
- `ds.lastValueData()` — often returns `{noData: true}` (unreliable)
- `ds.plots()` — plot metadata `{_items: [{index, value}]}`
- `ds.title()` — display title like `"RSI (14, close)"`
- `ds.getInputValues()`, `ds.getInputsInfo()`, `ds.getStyleInfo()` — study config

### avoid "temporary glitch"

Use `window.TradingViewApi.chart()` (the public API) instead of
`window.TradingViewApi._activeChartWidgetWV.value()` (the internal getter).
The internal getter triggers a "temporary glitch" warning popup that must
be dismissed by clicking the "Got it" button.

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
