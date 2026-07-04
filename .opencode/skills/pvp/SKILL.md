---
name: pvp
description: Periodic Volume Profile (PVP) development — Pine Script implementation matching TradingView's built-in Periodic Volume Profile at 100% POC parity. Use when editing or extending the custom PVP indicator.
---

# Periodic Volume Profile Development

Rules and gotchas for the custom PVP indicator at `pine_indicators/pvp.pine` and its parity testing.

## Architecture

The custom PVP is a Pine Script (v6) indicator that:
1. Fetches lower-TF bars via `request.security_lower_tf()` for sub-bar precision
2. Builds a volume histogram per period (Day/Week/Month)
3. Draws completed-period POCs as horizontal lines via `line.new()`  (plot 0 = period boundary marker)

**Rendering cap:** TV renders at most 50 `line.new` objects per indicator regardless of `max_poc_lines` input. The input controls in-Pine storage (FIFO deletion when exceeded) but TV's internal `_primitivesDataById` caps at 50 visible objects. `max_poc_lines` has `maxval=500` but anything above 50 is invisible.

## Implementation Rules

### Lower-TF data (`request.security_lower_tf`)

**Always use `array.concat()`, never `array.push()` with LTF arrays.**
In Pine v6, `array.push()` silently fails on arrays returned by `security_lower_tf`. Use `array.copy()` for initial assignment and `array.concat()` to append:

```pine
if is_new_period or na(period_start_bar)
    period_highs := array.copy(hs)       // initial assignment
    period_lows  := array.copy(ls)
    period_volumes := array.copy(vs)
else
    period_highs   := array.concat(period_highs, hs)  // append
    period_lows    := array.concat(period_lows, ls)
    period_volumes := array.concat(period_volumes, vs)
```

### Lower-TF string format

The string passed to `request.security_lower_tf` is the **tick aggregation period**, e.g. `"10"` for 10-minute bars inside 60m chart bars. The `f_lower_tf()` function computes this from the chart timeframe:

```pine
f_lower_tf() =>
    int min = int(timeframe.in_seconds(timeframe.period) / 60)
    if min <= 15    => "1"
    else if min <= 30 => "5"
    else if min <= 60 => "10"
    else if min <= 120 => "15"
    else if min <= 240 => "30"
    else              => "60"
```

### POC Computation

```pine
float poc_price = pls_min + (poc_row + 0.5) * tick_size
```

- `pls_min` = `array.min(period_lows)` — lowest low in the period
- `poc_row` = index of the highest-volume row in the histogram
- `tick_size` = `tpr_used * mintick` — the row height (adapted to fit `num_rows` rows)
- The `+ 0.5` centers the POC at the middle of the winning row

### Line Extension Logic

Replace `extend=extend.right` with per-bar extend/freeze using three parallel arrays:

```pine
var line[]  poc_lines   = array.new<line>()
var bool[]  poc_active  = array.new<bool>()   // true = still extending
var int[]   poc_period  = array.new<int>()     // bar_index when period started
```

On each bar, loop through active lines:
1. Get the line's POC price via `line.get_price(l, bar_index)`
2. If the current bar's `[low, high]` range crosses the POC price → freeze x2 at `bar_index[1]`, set `poc_active = false`
3. Otherwise → extend x2 to `bar_index`

```pine
if array.size(poc_lines) > 0
    for j = 0 to array.size(poc_lines) - 1
        if array.get(poc_active, j)
            int ps = array.get(poc_period, j)
            if bar_index > ps
                line l = array.get(poc_lines, j)
                float poc_price = line.get_price(l, bar_index)
                if not na(poc_price) and not na(high) and not na(low)
                    if high >= poc_price and low <= poc_price
                        line.set_x2(l, bar_index[1])
                        array.set(poc_active, j, false)
                    else
                        line.set_x2(l, bar_index)
```

## Gotchas (Known Issues)

### RE10119: `line.get_price` requires `xloc.bar_index`

```
Runtime error: line.get_price: Script tried to call line.get_price on a line
which was not created with xloc = xloc.bar_index.
```

Lines created with `xloc=xloc.bar_time` **cannot** be read by `line.get_price()`. Always use `xloc=xloc.bar_index` if you call `line.get_price()` on them.

```pine
// ✅ Correct
line l = line.new(bar_index[1], poc_price, bar_index, poc_price, xloc=xloc.bar_index, ...)
float p = line.get_price(l, bar_index)  // works

// ❌ Wrong
line l = line.new(time[1], poc_price, time, poc_price, xloc=xloc.bar_time, ...)
float p = line.get_price(l, bar_index)  // RE10119
```

### RE10045: `array.get()` on empty array (bar 0)

```
Runtime error: array.get: index 0 is out of bounds, array size is 0.
```

On bar 0, `poc_lines` is empty (`array.new<line>()`). Any access before the first `array.push()` raises this error. Guard the extend loop:

```pine
if array.size(poc_lines) > 0          // ← mandatory guard
    for j = 0 to array.size(poc_lines) - 1
        ...
```

### Year-alignment for Week/Month periods

`ta.change(time("12M"))` year-change detection is needed alongside `ta.change(time(f_period_tf()))` to handle the December→January transition correctly when period_unit is "Week" or "Month". Without it, year boundaries are missed because `time("W")`/`time("M")` don't cross the year boundary correctly.

### Max lines cap (30)

The `poc_lines` array is capped at 30 entries to prevent memory leaks. When exceeded:
```pine
if array.size(poc_lines) >= 30
    line.delete(array.shift(poc_lines))
    array.shift(poc_active)
    array.shift(poc_period)
```
All three parallel arrays must be shifted together.

## Reading POC Lines from CDP

Pine `line.new()` creates line objects stored in the study's renderer, NOT in `_data._items`. To read them programmatically:

```javascript
var ds = model.dataSourceForId(entityId);
var rData = ds._paneViews[1]._renderer._data;   // custom PVP uses index 1
var items = rData.items;                         // [{p1:{x,y}, p2:{x,y}, width, style}]
```

The `x`/`y` values are **pixel coordinates**. Convert to price via:
```javascript
var price = model.coordinateToPrice(y, priceScaleId);
```

The built-in PVP stores lines at `_paneViews[4]._data` — the index differs between built-in and custom Pine scripts.

## Reading POC lines via CDP

`tv.get_pine_lines(study_filter)` reads from `_primitivesDataById` via the internal getter path `_activeChartWidgetWV → _chartWidget.model().model().dataSources()[i]._graphics._primitivesCollection.dwglines.get("lines").get(false)._primitivesDataById`.

Gotchas:

1. **Name resolution:** USER; scripts (pine-facade deployed) expose their display name via `title()` method, not `metaInfo()`. The JS in `get_pine_lines` tries `title()` first, falls back to `metaInfo()`.
2. **`_primitivesDataById` format:** Can be either a `Map` with `.forEach()` or a plain object with numeric string keys. `Object.keys()` fallback is always used when `.forEach` is absent.
3. **Rendering cap & sorting:** TV renders max 50 `line.new` objects per indicator in `_primitivesDataById`. ``get_pine_lines(study_filter="...", sort_by="id")`` preserves chronological order and does NOT deduplicate by price. ``sort_by="price"`` (old default) sorts descending by price and deduplicates. PVP parity uses ``sort_by="id"`` — line IDs are sequential, so ``line[k]`` corresponds to the kth oldest visible completed-period POC.

## Parity Testing

```python
from pytvtools.indicator_parity import compare_pvp
from pytvtools import TV

async with TV() as tv:
    result = await compare_pvp(tv, "BATS:INTC", "60")
    print(f"{result['matched']}/{result['total']} ({result['match_rate']:.1f}%)")
    # Access the DataFrame for analysis
    df = result["pvp_df"]

    # Save a detailed text report for debugging
    result = await compare_pvp(tv, "BATS:INTC", "60", debug_path="pvp_report.txt")
```

The return dict includes a ``pvp_df`` key with a DataFrame containing columns:
``line_id, period_start, period_start_ts, period_end, period_end_ts,
custom_poc, builtin_poc, delta, match``.

Pass ``debug_path="path.txt"`` to write a human-readable comparison report
(mirrors the ``pvp_comparison_data.txt`` format).

Target: 100% POC match for completed periods at ±0.01 tolerance.

### Methodology

`compare_pvp()` uses the **custom PVP's ``Period Marker`` plot** (fires ``1.0``
at each new-period bar) to determine exact period boundaries — no heuristic
gap detection.

The comparison works as follows:

1. **Period markers** from the custom PVP's Plot 0 identify every period boundary.
2. **Built-in PVP** provides the completed-period POC: read its Plot 0
   (Developing POC) at the **last bar before each period marker** — that bar
   has accumulated ALL the period's volume, so the developing POC equals the
   completed period's POC.
3. **Custom PVP** provides completed-period POCs via
   ``get_pine_lines(study_filter="PVP_Custom", sort_by="id")``, which returns
   visible ``line.new`` objects in chronological creation order (oldest first).
4. **Positional matching**: line IDs are assigned sequentially at creation time,
   so ``sort_by="id"`` gives chronological ordering.  The N visible lines
   correspond to the N most recently completed periods:
   ``line[k] ↔ period [marker[-(N+1)+k], marker[-(N+1)+k+1]]``.  Periods older
   than TV's ~50-line rendering cap have no visible line and are excluded.

**Why this approach?**  The Period Marker gives exact boundaries (no threshold
tuning).  The built-in developing POC at period-end equals the completed-period
POC.  Positional matching avoids the fragility of price-proximity matching,
which can fail when two periods have similar POC prices.

**What NOT to do:**
- Do NOT compare all common timestamps (developing POC on intermediate bars
  differs between built-in and custom due to data pipeline timing)
- Do NOT use gap detection — it's a heuristic that fails on multi-session days
  or markets without overnight gaps
- Do NOT use price-proximity matching with ``sort_by="price"`` —
  ``get_pine_lines`` deduplicates by price level, and sorting destroys the
  chronological ordering needed for positional matching

## Environment Notes

- TV free tier limits to 2 indicators per chart — just enough for built-in PVP + custom PVP simultaneously
- PVP lines are only visible after at least one completed period boundary (depends on chart timeframe and visible range)
- Chart must have enough history loaded — scroll to earlier date if POC lines don't appear
