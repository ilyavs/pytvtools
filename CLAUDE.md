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
| `src/pytvtools/collector.py` | `Collector` — multi-symbol batch (CDP-based, studies too); `TVDataCollector` — OHLCV-only batch (no Chrome, wraps `get_ohlcv_multi`) |
| `src/pytvtools/watchlists.py` | `Watchlist` — frozen dataclass + predefined watchlists |
| `src/pytvtools/indicators.py` | Pure-Python SMA, EMA, RSI, MACD implementations |
| `src/pytvtools/indicator_parity.py` | `compare_indicator()` — verify Python vs TV indicator outputs match |
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
    multi = await d.get_ohlcv_multi(["NASDAQ:AAPL", "BINANCE:BTCUSDT"], "1D", 100)
```

### Authentication

| Method | Returns | Description |
|--------|---------|-------------|
| `is_logged_in()` | `bool` | Check if currently logged in to a TradingView account |
| `login(username=None, password=None, timeout=120)` | `dict` | Log in — programmatic (pass creds) or manual (omit creds, opens sign-in page for you) |
| `logout(timeout=10)` | `dict` | Sign out via the user avatar menu |

## All TV methods

- `is_logged_in()` → `bool`
- `login(timeout=120)` → `dict`
- `login(username, password, timeout=120)` → `dict`
- `logout(timeout=10)` → `dict`
- `get_state()` → `{symbol, timeframe, chartType}`
- `set_symbol(symbol, timeout=10, wait_data=True)` — `wait_data=False` skips chart-ready check
- `set_timeframe(tf)` — "D", "60", "15", etc.
- `set_chart_type(t)` — Candles=1, Line=2, Area=3
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
- `batch(symbols, timeframes, action, max_bars=500)` — multi-symbol scan (CDP-based, handles rate limits)
- `get_ohlcv_multi(symbols, interval, bars_count, summary, max_concurrent=10)` — parallel WS fetch, no Chrome needed
- `pine_set_source(source)` — inject Pine code
- `pine_compile()` — compile and read errors
- `get_pine_source(study_id, entity_id=None)` — fetch Pine Script source of any public indicator
- `replay_start(date=None)` — enter bar-replay mode (optionally at a specific date)
- `replay_stop()` — exit replay mode, return to realtime
- `replay_status()` → `{is_replay_started, current_date, ...}`
- `replay_step()` — advance one bar in replay mode
- `replay_autoplay(speed=0)` — toggle autoplay, optionally set delay (ms)

## MCP server (optional, host-side)

```bash
# pip install pytvtools[mcp]
# then run: pytvtools-mcp
```

Registers all TV methods as MCP tools. Runs **on the host** (not in Docker)
and connects to Chrome at `localhost:9222` (Docker port mapping).

### Credential resolution

The ``login`` MCP tool resolves credentials in this order:

1. **Config file** — ``~/.tv/config`` (or ``$TV_CONFIG_PATH``) with a
   ``username`` and ``password`` key, e.g. ``{"username": "…", "password": "…"}``.
2. **Environment variables** — ``TV_USERNAME`` and ``TV_PASSWORD``.
3. **Manual mode** — navigates to the sign-in page and waits for you to type.

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

## TVDataCollector (CDP-free, OHLCV only)

```python
from pytvtools import TVDataCollector

collector = TVDataCollector(
    symbols=["SP:SPX", "COINBASE:BTCUSD"],
    timeframes=["1D", "60"],
    bars_count=500,
    max_concurrent=3,
)
result = await collector.run()
path = collector.export_parquet("data.parquet")
path = collector.export_json("data.json")
```

Same record schema as Collector (no `st_` study columns). No Chrome needed — pure WebSocket via TVData.

## Collector (multi-symbol, CDP-based, studies too)

```python
from pytvtools import Collector, CollectorConfig

config = CollectorConfig(
    symbols=["NASDAQ:AAPL", "BINANCE:BTCUSDT"],
    timeframes=["1D", "60"],
    actions=["ohlcv", "studies"],
    max_bars=1000,
)
collector = Collector(config)
async with TV() as tv:
    result = await collector.run(tv)
path = collector.export_parquet("data.parquet")
# JSON (no extra deps, always available)
path = collector.export_json("data.json")
```

Record schema (parquet/JSON):
- `symbol`, `timeframe`, `scan_ts` — identification
- `ohlcv_count`, `ohlcv_high`, `ohlcv_low`, `ohlcv_open`, `ohlcv_close`, `ohlcv_avg_volume`, `ohlcv_range` — OHLCV summary stats
- `st_<study name>` — latest value for each indicator (prefixed with `st_`)

## Python indicators

```python
from pytvtools.indicators import sma, ema, rsi, macd, mfi

bars = await tv.get_ohlcv(count=500, summary=False)
closes = [b["close"] for b in bars]
rsi_vals = rsi(closes, period=14)  # [None]*14 + float values, Wilder's smoothing
sma_vals = sma(closes, period=20)
ema_vals = ema(closes, period=20)
macd_vals = macd(closes, fast=12, slow=26, signal=9)
# Volume-based: pass full OHLCV bars
mfi_vals = mfi(bars, period=14)
```

## Adding a new indicator (Python + TV parity)

1. **Implement** in `indicators.py`. Accept `list[float] | list[dict[str, Any]]`:
   - Close-only: `_prices(data)` extracts `"close"` from dict bars, returns `list[float]`
   - Multi-column (MFI, OBV, etc.): extract `high`/`low`/`close`/`volume` directly from dict bars inline; raise `ValueError` if given flat floats
   - Return `list[float | None]` with leading `None`s

2. **Register** in `indicator_parity.py`:
   - Add to `_BUILTIN_COMPUTERS` with canonical TV study ID (e.g. `"STD;Money_Flow": mfi`)
   - Add alias in `_STUDY_ID_ALIASES` if user-facing name differs (e.g. `"STD;MFI" → "STD;Money_Flow"`)
   - No special branch needed in `compare_indicator` — it always passes `bars`; `_prices()` handles close-only extraction

3. **Test parity**:
   ```python
   from pytvtools.indicator_parity import compare_indicator
   report = await compare_indicator(tv, "BINANCE:BTCUSDT", "1D", "STD;<id>")
   ```
   Target >99% match at ±0.01 tolerance. The function waits up to 7.5s for indicator data after adding it.

## Indicator parity (Python vs TradingView)

```python
from pytvtools import TV
from pytvtools.indicator_parity import compare_indicator

async with TV() as tv:
    report = await compare_indicator(tv, "BINANCE:BTCUSDT", "1D", "STD;RSI")
    print(report.summary())
    # Total bars, match rate, mismatches
```

## Remote tunnel

```bash
ssh -L 9222:localhost:9222 user@oracle-arm-instance
```
