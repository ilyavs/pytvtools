# Periodic Volume Profile Pine Script — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replicate TradingView's built-in Periodic Volume Profile as a Pine Script indicator in `pine_indicators/pvp.pine`, registered in `pine_parity.py` with a custom comparison function.

**Architecture:** Single Pine Script v6 file using `request.security_lower_tf()` for intra-bar data, custom arrays for volume row management, `plot()` for POC/VAH/VAL parity outputs, and `line.new()` for extend-right visual lines. Custom parity comparison in `pine_parity.py` that reads our plot outputs and the built-in's lines separately.

**Tech Stack:** Pine Script v6, Python 3.10+

## Global Constraints

- Pine Script `//@version=6` mandatory
- Indicator title: `"Custom PVP"`, shorttitle: `"PVP_Custom"`, overlay: true
- All inputs use typed `input.int()`, `input.bool()`, `input.string()` with appropriate options
- LTF resolution table must match TV's published spec exactly
- Parity comparison function `compare_pine_pvp()` reads both `get_indicator_data()` and `get_pine_lines()`
- Volume distribution across rows uses proportional overlap weighting
- Period boundaries use `change(time())` with formatted timeframe strings
- 4-space indentation in Pine Script

---

### Task 1: Pine Script — Complete PVP indicator

**Files:**
- Create: `pine_indicators/pvp.pine`

**Interfaces:**
- Produces: Complete, compilable Pine Script `//@version=6` indicator
  - Inputs: period_mult, period_unit, volume_mode, va_pct, num_rows, extend_poc
  - Internal functions: `f_get_ltf()`, `f_get_period_tf()`, `f_reset_rows()`, `f_distribute_volume()`, `f_calc_poc()`, `f_calc_vah_val()`
  - plot() outputs: "POC" (purple, width=2), "VAH" (blue, width=1), "VAL" (blue, width=1)
- Consumes: Nothing (first task)

- [ ] **Step 1: Write the complete Pine Script to `pine_indicators/pvp.pine`**

The script must implement:

**Inputs:**
```pine
period_mult = input.int(1, "Period", minval=1, group="Volume Profile")
period_unit = input.string("Day", "Period Unit", options=["Day", "Week", "Month"], group="Volume Profile")
volume_mode = input.string("Total", "Volume", options=["Total", "Up/Down", "Delta"], group="Volume Profile")
va_pct      = input.int(70, "Value Area Volume", minval=50, maxval=99, group="Rows")
num_rows    = input.int(24, "Number of Rows", minval=5, maxval=100, group="Rows")
extend_poc  = input.bool(true, "Extend POC Right", group="Display")
```

**LTF resolution table (exact copy from TV docs):**
```pine
f_get_ltf() =>
    if timeframe.isseconds
        if timeframe.multiplier <= 10
            "1S"
        else if timeframe.multiplier <= 15
            "5S"
        else
            "15S"
    else if timeframe.isintraday
        int n = timeframe.multiplier
        if n <= 4
            "1"
        else if n <= 15
            "1"
        else if n <= 30
            "5"
        else if n <= 60
            "10"
        else if n <= 120
            "15"
        else if n <= 240
            "30"
        else
            "60"
    else if timeframe.period == "D"
        "5"
    else if timeframe.period == "W"
        "30"
    else
        "120"   // Month
```

**Period detection:**
```pine
f_get_period_tf(string unit, int mult) =>
    if unit == "Day"
        str.tostring(mult) + "D"
    else if unit == "Week"
        str.tostring(mult) + "W"
    else if unit == "Month"
        str.tostring(mult) + "M"
    else
        "1D"
```

**Row arrays (var, reset on period boundary):**
- `row_high`, `row_low`, `row_volume`, `row_buy_vol`, `row_sell_vol` — all float arrays sized to `num_rows`
- `f_reset_rows(hist_high, hist_low, num_rows)` — initialize row boundaries and zero volumes
  - Row height = `(hist_high - hist_low) / num_rows`, rounded to `syminfo.mintick`

**Volume distribution (`f_distribute_volume`):**
For each LTF bar in `request.security_lower_tf()` result:
1. Find start/end row indices the LTF bar spans
2. For each spanned row, compute overlap as fraction of total LTF bar range
3. Distribute volume proportionally: `vol_share = ltf_volume * overlap / total_span`
4. For Up/Down mode: if close > open → buy_vol else sell_vol

**POC/VAH/VAL calculation:**
- POC: find row index with max volume; price = midpoint of that row's high/low
- VAH/VAL: expand from POC outward accumulating volume until VA% reached
  - Always expand to the side with more volume first
  - VAH = high of highest row in value area
  - VAL = low of lowest row in value area

**Main execution flow:**
1. Detect new period: `is_new_period = change(time(period_tf)) or bar_index == 0`
2. On new period: call `f_reset_rows()` using high/low from recent history
3. On period boundary (but before reset): calculate POC/VAH/VAL for completed period
4. Each bar: fetch LTF data, loop through LTF array, call `f_distribute_volume()` for each
5. `plot()` POC, VAH, VAL
6. If `extend_poc`: draw `line.new()` extending right from period start; check for price cross and delete if crossed

**Visual elements (drawn only on last bar via `barstate.islast`):**
- `box.new()` per row showing volume histogram
- Color: buy volume green, sell volume red (or just one color for Total mode)

- [ ] **Step 2: Self-review the implementation**
  - Verify LTF table matches TV spec
  - Check POC/VAH/VAL calculation logic
  - Verify `request.security_lower_tf()` usage is correct for Pine v6
  - Ensure all arrays are properly initialized and managed
  - Check that `plot()` calls have correct plot names for parity

- [ ] **Step 3: Commit**

```bash
git add pine_indicators/pvp.pine
git commit -m "feat: add Periodic Volume Profile Pine Script"
```

---

### Task 2: Python — Parity framework registration

**Files:**
- Modify: `src/pytvtools/pine_parity.py`

**Interfaces:**
- Consumes: `pvp.pine` from Task 1, existing `compare_indicator()` pattern from `indicator_parity.py`
- Produces: `_PINE_INDICATORS["pvp"]` entry, `compare_pine_pvp()` async function

- [ ] **Step 1: Register in `_PINE_INDICATORS`**

Add entry to `_PINE_INDICATORS` in `pine_parity.py`:
```python
"pvp": {"file": "pvp.pine", "study_id": None, "plot_index": 0},
```

- [ ] **Step 2: Implement `compare_pine_pvp()` in `pine_parity.py`**

The function:
1. Sets symbol/timeframe, removes all indicators
2. Adds custom PVP (via Pine Editor injection using `_pine_add_script()` or `add_indicator()`)
3. Reads POC/VAH/VAL plot values via `get_indicator_data()`
4. Removes custom PVP
5. Adds built-in "Periodic Volume Profile" indicator
6. Reads built-in PVP's line values via `get_pine_lines()` filtering for "POC", "VAH", "VAL" text
7. Removes built-in PVP
8. Compares the two datasets bar-by-bar
9. Returns `ParityReport`

```python
async def compare_pine_pvp(
    tv,
    symbol="BINANCE:BTCUSDT",
    timeframe="1H",
    period=(1, "Day"),
    va_pct=70,
    num_rows=24,
):
    from pytvtools.indicator_parity import ParityReport, Mismatch
    import asyncio

    mismatches = []
    total = matched = 0

    await tv.set_symbol(symbol)
    await tv.set_timeframe(timeframe)
    await tv.remove_all_indicators()
    await tv.wait_for_chart_ready()

    # Step 1: Add custom PVP via Pine Editor
    await tv._ui_click("Pine Editor")  # open editor
    source = get_pine_indicator_source("pvp")
    custom_eid = await _pine_add_script(tv, source)
    await asyncio.sleep(3)

    # Read POC/VAH/VAL from our script
    our_data = await tv.get_indicator_data(custom_eid)
    # Extract POC, VAH, VAL plots

    await tv.remove_all_indicators()

    # Step 2: Add built-in PVP
    builtin_eid = await tv.add_indicator("Periodic Volume Profile")
    await asyncio.sleep(3)

    # Read lines from built-in
    lines = await tv.get_pine_lines()
    # Filter by text

    await tv.remove_all_indicators()

    # Step 3: Compare
    # ... bar-by-bar comparison ...

    return ParityReport(...)
```

- [ ] **Step 3: Commit**

```bash
git add src/pytvtools/pine_parity.py
git commit -m "feat: register PVP in parity framework"
```
