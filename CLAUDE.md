# pytvtools — Agent Guide

Pure Python CDP library for TradingView in Chrome. No Node.js, no submodules.

> **Start here:** [`DEVELOPMENT.md`](DEVELOPMENT.md) — container setup, command patterns,
> architecture, and implementation rules every agent must follow before editing code.

## Key modules

| File | What |
|------|------|
| `src/pytvtools/cdp.py` | `CdpConnection` — WebSocket transport for CDP `Runtime.evaluate` |
| `src/pytvtools/chrome.py` | `Chrome` — launch/stop/restart headless Chrome with CDP |
| `src/pytvtools/tv.py` | `TV` — high-level TradingView client (CDP-based) |
| `src/pytvtools/tvdata.py` | `TVData` — direct WebSocket OHLCV fetcher (no CDP, fast) |
| `src/pytvtools/collector.py` | `Collector` — multi-symbol batch data collection + parquet/JSON export |
| `src/pytvtools/watchlists.py` | `Watchlist` — frozen dataclass + predefined watchlists (SPDR sectors, industries) |
| `src/pytvtools/__init__.py` | Re-exports |

## Usage

```python
from pytvtools import TV, TVData, Chrome, wait_for_cdp

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

# Option C: direct WebSocket (no Chrome needed, OHLCV only)
async with TVData() as d:
    bars = await d.get_ohlcv("NASDAQ:AAPL", "1D", 100)
    summary = await d.get_ohlcv("BINANCE:BTCUSDT", "1D", 500, summary=True)
```

## All TV methods

- `get_state()` → `{symbol, timeframe, chartType}`
- `set_symbol(symbol)`
- `set_timeframe(tf)` — "D", "60", "15", etc.
- `set_chart_type(t)` — Candles=1, Line=2, etc.
- `scroll_to_date(date)` — "2025-01-15" or unix ts
- `get_visible_range()` → `{from, to}`
- `get_ohlcv(count=500, summary=False)` → bars or stats
- `get_quote()` → `{symbol: str}`
- `wait_for_chart_ready(expected_symbol=None, timeout=10)` → `bool`
- `get_study_values()` → `{name: {title, values: [{timestamp, value}]}}`
- `get_indicator_data(entity_id)` → all historical plot values per plot name
- `search_indicators(query)` → `[{id, name, study_id}]`
- `add_indicator(indicator, inputs=None)` → entity ID (e.g. `"STD;RSI"`, `"PUB;85"`)
- `remove_indicator(entity_id)`
- `remove_all_indicators()`
- `set_indicator_inputs(entity_id, inputs)`
- `get_indicator_count()` → `int`
- `list_templates(tab=None)` → `[{name, description}]` — tab: "my templates", "technicals", "financials"
- `apply_template(name)` — apply a saved indicator template (searches all tabs)
- `capture_screenshot()` → base64 PNG
- `get_pine_lines(study_filter=None)` → price levels
- `get_pine_labels(study_filter=None, max_labels=50)` → text labels
- `get_pine_boxes(study_filter=None)` → price zones
- `get_pine_tables(study_filter=None)` → formatted text rows
- `batch(symbols, timeframes, action)` — multi-symbol scan (CDP-based, handles rate limits)
- `pine_set_source(source)` — inject Pine code
- `pine_compile()` — compile and read errors
- `set_symbol(symbol, timeout=10, wait_data=True)` — `wait_data=False` skips chart-ready check

## MCP server (optional)

```bash
# pip install pytvtools[mcp]
# then run: pytvtools-mcp
```

Registers all TV methods as MCP tools.

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
- `_createStudy({type: "pine", pineId: "STD;Name"})` — built-in pine studies (most common)
- `_createStudy({type: "java", studyId: "Name@tv-basicstudies"})` — java-type built-ins (Volume, VWAPAA)

### Adding indicators

```javascript
// Built-in (pine) — most common
var eid = await chart()._createStudy({type: "pine", pineId: "STD;RSI"});
// eid is the entity ID string e.g. "2tMAgd"

// Built-in (java) — Volume, VWAPAA, etc.
var eid = await chart()._createStudy({type: "java", studyId: "RSI@tv-basicstudies"});

// Community script (Pine Script from TradingView's platform)
var eid = await chart()._createStudy({type: "pine", pineId: "PUB;85"});

// Display name — fallback (triggers metadata request)
var eid = await chart().createStudy("Relative Strength Index");
```

Study ID format:

| Pattern | Example | Type |
|---------|---------|------|
| `STD;Name` | `STD;RSI`, `STD;SMA`, `STD;MACD` | Built-in (pine) |
| `Name@tv-basicstudies` | `Volume@tv-basicstudies`, `VWAPAA@tv-basicstudies` | Built-in (java) |
| `PUB;id` | `PUB;85`, `PUB;ULSu...` | Community script |
| `PUB;Name` | `PUB;Relative Strength Index` (from createStudy) | Display name fallback |

Prefer `STD;` IDs returned by `search_indicators` for built-in studies.

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

## Collector (multi-symbol + parquet export)

```python
from pytvtools import Collector, CollectorConfig

config = CollectorConfig(
    symbols=["NASDAQ:AAPL", "BINANCE:BTCUSDT"],
    timeframes=["1D", "60"],
    actions=["ohlcv", "studies"],  # or ["ohlcv"] for OHLCV-only
)
collector = Collector(config)
async with TV() as tv:
    result = await collector.run(tv)          # returns CollectResult
path = collector.export_parquet("data.parquet")
# JSON (no extra deps, always available)
path = collector.export_json("data.json")
```

Record schema (parquet/JSON):
- `symbol`, `timeframe`, `scan_ts` — identification
- `ohlcv_count`, `ohlcv_high`, `ohlcv_low`, `ohlcv_open`, `ohlcv_close`, `ohlcv_avg_volume`, `ohlcv_range` — OHLCV summary stats
- `st_<study name>` — latest value for each indicator (prefixed with `st_`)

## Remote tunnel

```bash
ssh -L 9222:localhost:9222 user@oracle-arm-instance
```
