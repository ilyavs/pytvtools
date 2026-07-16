---
name: pine-develop
description: Full Pine Script development loop for the pytvtools repo — write code, deploy via facade or editor, read output, fix runtime errors, handle Studio quirks.
---

# Pine Script Development — pytvtools

Full development lifecycle for Pine Script indicators in the pytvtools repo: write → deploy → read output → fix errors → iterate.

### MCP tools (additional read methods)

Some read methods — `get_pine_tables`, `get_pine_boxes`, `get_equity`, `get_trades`, `get_strategy_results` — are **not implemented in `tv.py`** but are available via the `tradingview` MCP server (`tradingview-mcp-jackson`). Use `tool_use` blocks with the server name `tradingview` to call them (e.g. `tradingview_data_get_pine_tables`, `tradingview_data_get_pine_boxes`).

## 1. Quick Start: Deployment

Two deployment paths:

### Preferred: `pine_facade_deploy` (bypasses Pine Editor)

Saves via REST API + adds via `_createStudy`. **Always pass a unique `name`** — TV caches by shorttitle, so `pine_facade_deploy(source, name="CL_Levels_v2")` forces a fresh compile; reusing the same name returns the cached old version.

**IMPORTANT:** The REST API compiler is stricter than `pine_check`. Always extract Pine function calls (`ta.change()`, `ta.cross()`, etc.) to variables before passing into conditional expressions:

```pine
// BROKEN — Syntax error via pine_facade_deploy
f_new_line(..., en1 and ta.change(time(p1)) != 0)

// FIXED
t1 = ta.change(time(p1)) != 0
f_new_line(..., en1 and t1)
```

**Also:** If the indicator only draws `line.new`/`label.new` (no `plot()`), add a dummy plot or it reports `hasError: true`:

```pine
plot(na, title="dummy")  // suppress hasError for line.new-only indicators
```

```python
source = open("pine_indicators/my_indicator.pine").read()
eid = await tv.pine_facade_deploy(source, name="MyInd_v1")
# Returns entity ID like "2tMAgd"
```

Name is auto-extracted from `indicator(title=...)` if omitted, but then caching applies.

### Fallback: Pine Editor (`pine_set_source` + `pine_compile`)

```python
await tv.pine_set_source(source)
result = await tv.pine_compile()  # finds Add/Update buttons, Ctrl+Enter fallback
# result = {button_clicked, has_errors, errors, runtime_errors, study_added}
```

### After deploy: verify study state

```python
await tv._eval("""
(function() {
    var study = TradingViewApi.chart().getStudyById("ENTITY_ID");
    return {
        dataLength: study.dataLength(),   // >0 means data loaded
        isLoading: study.isLoading(),     // false when done
        hasError: study.hasError()        // true if runtime error
    };
})()
""")
```

## 2. Reading Output from Custom Indicators

### `get_pine_lines` — horizontal price levels (`line.new`)

```python
lines = await tv.get_pine_lines(study_filter="PVP_Custom", sort_by="id")
# Returns [{id, price, text}] — sort_by="id" = chronological, no dedup
#           sort_by="price" = descending, deduplicated
```

Access path internally (not public chart API):
```
ds._graphics._primitivesCollection.dwglines.get("lines").get(false)._primitivesDataById
```

### `get_pine_labels` — text annotations (`label.new`)

```python
labels = await tv.get_pine_labels(study_filter="MyInd", max_labels=50)
# Returns [{text, price, time}]
```

Uses the public chart API: `chart().chartWidget().activeChart().getAllLabels()`.

### `get_pine_tables` / `get_pine_boxes` — MCP only

See MCP tools note at top of this skill. These are available via `tradingview_data_get_pine_tables` / `tradingview_data_get_pine_boxes` on the `tradingview` MCP server, not in `tv.py`.

### `get_indicator_data` — all historical plot values

```python
data = await tv.get_indicator_data(entity_id)
# Returns {id, title, count, plots: [{name, values: [{timestamp, value}]}]}
```

Reads from `ds._data._items` directly — all bars, all plots. Only works for indicators with standard `plot()` outputs (not `line.new`/`label.new` only).

### `get_study_values` — current values only

```python
vals = await tv.get_study_values()
# {name: {title, values: [{timestamp, value}]}} — last value per study
```

## 3. Compilation & Errors

### Runtime errors

```python
# Fast check — scans DOM + study compile-error status
errors = await tv.check_pine_runtime_errors()
# [{study_id?, study_name?, message, source}]

# Detailed — reads full error code, description, stack trace, clicks exclamation icon
details = await tv.check_pine_runtime_errors_detailed(indicator_name="PVP_Custom")
# {errors: [{indicator, study_id, message}], total: N, popup_text: "..."}
```

### Compilation warnings (severity 4)

Warnings about conditional `ta.change()` or `f_new_line` calls are **non-blocking**. They don't prevent deployment or affect runtime behavior.

### Fetching source from public indicators

```python
source = await tv.get_pine_source("PUB;85")
source = await tv.get_pine_source("PUB;85", entity_id=eid)  # faster if on chart
```

Three strategies: chart model → REST API (`/pine_script/public/{id}`) → script page scrape.

## 4. Common Pine Script Pitfalls

### `for` loop on empty array (runtime error RE10045)

Pine Script executes `for j = 0 to size - 1` once **even when `size == 0`** (range `0 to -1` is treated as one iteration). **Always guard with `if size > 0`**:

```pine
f_check_lines(la, active, prices) =>
    int size = array.size(la)
    if size > 0  // REQUIRED — prevents "index 0 out of bounds"
        for j = 0 to size - 1
            ...
```

### Pine v6: `array.push()` silently fails with `security_lower_tf` arrays

Never use `for`-loop + `array.push()` with arrays returned by `request.security_lower_tf`. Always use `array.copy()` for initial assignment and `array.concat()` to append:

```pine
if is_new_period or na(period_start_bar)
    period_highs := array.copy(hs)
else
    period_highs := array.concat(period_highs, hs)
```

### PVP volume distribution tick math

Volume per tick level = `bar_volume / (num_ticks + 1)`, NOT `bar_volume / num_ticks`. The `+1` accounts for the inclusive range `[low, high]` which spans `nt + 1` tick levels. Without this, volume is over-allocated.

```pine
int nt = int((high - low) / mintick)
int n_levels = nt + 1
float vpt = bar_volume / n_levels
```

### PVP POC formula (center-of-row)

```pine
float poc_price = pls_min + (poc_row + 0.5) * tick_size
```

### `line.get_price` requires `xloc.bar_index`

Lines created with `xloc=xloc.bar_time` cannot be read by `line.get_price()` (RE10119). Always use `xloc=xloc.bar_index` if calling `line.get_price()`:

```pine
line l = line.new(bar_index[1], poc_price, bar_index, poc_price, xloc=xloc.bar_index, ...)
float p = line.get_price(l, bar_index)  // works
```

### TV rendering cap for line.new

TV renders at most ~50 `line.new` objects per indicator in `_primitivesDataById`. Anything above 50 is invisible regardless of `max_lines` input.

## 5. Connection Management

### "Restore connection" button

After too many study add/remove cycles, TV's data feed drops. A "Restore connection" button appears at the bottom of the chart. **Symptom:** studies stuck on `isLoading: true` indefinitely.

To recover, click the button via:

```javascript
var btn = document.querySelector('[class*="restoreConnection"]');
if (btn) btn.click();
```

After restoration, `_data._items` populates normally.

## 6. Line-vs-Marker Alignment (PVP-specific)

`get_pine_lines(study_filter="PVP_Custom", sort_by="id")` can return more visible lines (up to TV's ~55 cap) than completed periods. The alignment formula is:

```python
n_periods = min(N, len(marker_tss) - 1)      # clamp to available periods
offset = N - n_periods                         # skip oldest lines beyond marker range
line = lines[offset + k]                      # aligns line[k] with marker[-(n_periods+1)+k]
```

Do NOT change these formulas without re-verifying all three period units (Day/Week/Month). The off-by-one between N+1 vs N and the `offset` were hard-won fixes.

## 7. Indicator Limits & Cleanup

- Default max indicators: 2 (configurable via `TV_MAX_INDICATORS` env var)
- `TooManyIndicatorsError` raised when exceeded
- Always `remove_all_indicators()` between tests

## 8. Study ID Formats

| Pattern | Example | Type |
|---------|---------|------|
| `STD;Name` | `STD;RSI`, `STD;SMA` | Built-in (pine) |
| `Name@tv-basicstudies` | `Volume@tv-basicstudies` | Built-in (java) |
| `PUB;id` | `PUB;85` | Community script |
| `USER;id` | `USER;abc123` | Saved via `pine_facade_deploy` |

### Adding indicators

```python
eid = await tv.add_indicator("STD;RSI")                    # built-in pine
eid = await tv.add_indicator("Volume@tv-basicstudies")     # built-in java
eid = await tv.add_indicator("PUB;85")                      # community
eid = await tv.add_indicator("STD;RSI", inputs={"length": 20})  # with inputs
```

### Searching

```python
results = await tv.search_indicators("Relative Strength")  # [{id, name, study_id}]
```

### Modifying inputs

```python
await tv.set_indicator_inputs(entity_id, {"length": 20})
```

### Removing

```python
await tv.remove_indicator(entity_id)
await tv.remove_all_indicators()
```

## 9. JS API Reference (CDP context)

### Public chart API (preferred — avoids "temporary glitch")

```javascript
window.TradingViewApi.chart()
```

Methods: `getState()`, `setSymbol()`, `setResolution()`, `setChartType()`, `getAllStudies()`, `getStudyById(id)`, `getSeries(id)`, `removeEntity(id)`, `removeAllStudies()`, `chartWidget()`, `_createStudy({...})`.

### Adding to chart via CDP

```javascript
// Built-in pine
var eid = await chart()._createStudy({type: "pine", pineId: "STD;RSI"});

// Built-in java
var eid = await chart()._createStudy({type: "java", studyId: "RSI@tv-basicstudies"});

// Community
var eid = await chart()._createStudy({type: "pine", pineId: "PUB;85"});
```

### Reading indicator data directly

```javascript
var ds = chart().chartWidget().model().dataSourceForId(entityId);
var items = ds._data._items;  // [{index, value: [timestamp, plotValue]}]
```

Key properties:
- `ds._data._items` — all plot values
- `ds.plots()` — plot metadata
- `ds.title()` — display title (e.g. "RSI (14, close)")
- `ds.getInputValues()`, `ds.getInputsInfo()`, `ds.getStyleInfo()` — config
- `ds._compileErrorStatus` — error object if runtime error
- `ds._status._value` — status with `errorDescription` for detailed errors
