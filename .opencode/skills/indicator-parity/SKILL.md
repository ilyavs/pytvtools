---
name: indicator-parity
description: Add a new indicator with Python + Pine Script implementations, register in parity framework, and verify 100% match against TradingView's built-in. Use when the task is to parity-match a new indicator.
---

# Indicator Parity Workflow

Add a new indicator with Python and Pine Script implementations, register in the parity framework, and verify 100% match (±0.01) against TradingView's built-in.

## Architecture

| Layer | File | Role |
|-------|------|------|
| Python impl | `src/pytvtools/indicators.py` | Pure Python computation |
| Pine ref | `pine_indicators/<name>.pine` | Reference Pine Script (mimics built-in) |
| Python≤>TV bridge | `src/pytvtools/indicator_parity.py` | Maps TV study ID → Python function, inputs, plot names |
| Pine≤>TV bridge | `src/pytvtools/pine_parity.py` | Registers Pine files for pine-vs-built-in comparison |

## Workflow

### 1. Research the indicator before writing code

**Do not guess the formula or implementation from memory.** TradingView's built-in indicators often use non-standard smoothing, unique parameter defaults, or undocumented edge-case handling. Instead:

1. **Search TradingView's Pine Script reference** for the indicator's exact formula:
   - Go to `https://www.tradingview.com/pine-script-reference/v6/` and search for the indicator name
   - Look for the built-in function documentation (e.g. `ta.atr`, `ta.rsi`, `ta.bb`)
   - Note the exact smoothing method, warmup period, and edge-case behavior
2. **Use `websearch` to find community-verified parity discussions** if the official docs are unclear — search for "TradingView <indicator> formula" or "pine script <indicator> implementation".
3. **Cross-reference against the public TradingView chart source** via the Pine Editor: open a new indicator, type the built-in call, compile, and inspect the calculated values if needed.

### 2. Discover the TV study ID and input mapping

```python
# Interactive session — run this to find the real study ID and input IDs
await tv.set_symbol("BINANCE:BTCUSDT")
await tv.set_timeframe("1D")
await tv.remove_all_indicators()

eid = await tv.add_indicator("STD;<best_guess_id>")  # or search_indicators()
# Read input layout:
js = """
(function() {
    var study = TradingViewApi.chart().getStudyById(__EID__);
    if (!study) return null;
    var vals = study.getInputValues ? study.getInputValues() : [];
    return vals.map(function(v) { return {id: v.id, name: v.name, value: v.value, type: v.type}; });
})()
""".replace("__EID__", repr(eid))
await tv._eval(js)
```

Common TV study IDs differ from short names:
- `STD;Bollinger_Bands` (not `STD;BB`)
- `STD;Average_True_Range` (not `STD;ATR`)
- `STD;Stochastic_RSI` (not `STD;SRSI`)
- `STD;Money_Flow` (not `STD;MFI`)

Input ID order doesn't always match order in the settings panel — read the raw IDs from `getInputValues()`.

### 3. Implement Python function in `src/pytvtools/indicators.py`

**Conventions:**
- First param `data: list[float] | list[dict[str, Any]]` — use `_prices(data)` for close-only, extract inline for multi-column
- Returns `list[float | None]` (single-plot) or `dict[str, list[float | None]]` (multi-plot)
- Leading `None`s for warmup period; match TV's NaN handling exactly
- Use SMA/RMA as TV uses (not EMA unless TV uses EMA)
- Register in `__all__` if new helper is public (not needed for internal helpers)

```python
def my_indicator(data, period=14):
    prices = _prices(data)
    result = [None] * len(prices)
    for i in range(period - 1, len(prices)):
        # computation
        result[i] = value
    return result
```

For multi-column:
```python
def my_indicator(data, period=14, ...):
    prices = _prices(data)
    upper = [None] * len(prices)
    lower = [None] * len(prices)
    # ... compute ...
    return {"upper": upper, "lower": lower}
```

### 4. Write Pine Script in `pine_indicators/<name>.pine`

Pine `//@version=6`. Must declare `indicator()` with matching plot count and names.

```pine
//@version=6
indicator(title="Custom <Name>", shorttitle="<Name>_Custom", format=format.price, precision=2)

length = input.int(14, "Length")
src = input.source(close, "Source")

val = ...  # computation matching TV built-in

plot(val, "<Plot Name>", color=color.blue)
```

Plot names in Pine's `plot()` call must match the plot names read from TV's built-in (check with `get_indicator_data(eid)`).

### 5. Register in `src/pytvtools/indicator_parity.py`

Edit four registries:

```python
# 5a. _BUILTIN_COMPUTERS — TV study ID → Python function
"STD;My_Indicator": my_indicator,

# 5b. _TV_INPUT_MAP — TV input IDs → Python parameter names
#     (discover IDs in step 2)
"STD;My_Indicator": {"in_0": "period", "in_1": "source_param"},

# 5c. _PLOT_KEY_MAP — TV plot names → Python dict keys (only for multi-plot)
"STD;My_Indicator": {"Upper": "upper", "Lower": "lower"},

# 5d. _STUDY_ID_ALIASES — convenience aliases
"MY_IND": "STD;My_Indicator",
"STD;MY": "STD;My_Indicator",
```

Also update the import at the top of `indicator_parity.py`:
```python
from pytvtools.indicators import rsi, sma, ema, macd, mfi, bbands, atr, srsi, my_indicator
```

### 6. Register in `src/pytvtools/pine_parity.py`

```python
_PINE_INDICATORS: dict[str, dict[str, Any]] = {
    ...
    "my_indicator": {
        "file": "my_indicator.pine",
        "study_id": "STD;My_Indicator",
        "plot_index": 0,  # which plot to compare by default
    },
}
```

The `name` key in `_PINE_INDICATORS` becomes the `pine_name` argument to `compare_pine_indicator()`.

### 7. Test parity

```python
from pytvtools import TV
from pytvtools.indicator_parity import compare_indicator
from pytvtools.pine_parity import compare_pine_indicator

async with TV() as tv:
    # Remove all indicators first (2-indicator limit)
    await tv.remove_all_indicators()

    # Python vs TV built-in
    report = await compare_indicator(
        tv, "BINANCE:BTCUSDT", "1D", "STD;My_Indicator"
    )
    print(report.summary())
    # Target: 100% match, 0 mismatches, ±0.01 tolerance

    # Multi-plot: check each plot by index
    for pi in range(3):
        r = await compare_indicator(tv, "BINANCE:BTCUSDT", "1D", "STD;My_Indicator", plot_index=pi)
        print(r.summary())
```

If mismatches exist:
1. Check TV's actual computation (compare Pine ref vs built-in)
2. Verify input values match (`_TV_INPUT_MAP`)
3. Add tolerance or fix Python logic
4. For recursive indicators (EMA, Wilder's RSI), ensure the chart loads enough history (zoom out)

### 8. Run unit tests

```bash
docker exec -w /app docker-pytvtools-1 python -m pytest tests/ -m "not integration" -v 2>&1 | tail -20
```

All indicator tests (`test_indicators.py`, `test_indicator_parity.py`, `test_pine_parity.py`) must pass clean.

### 9. Cleanup

Before committing, clean up the working tree:

1. **Remove temp/debug scripts** — any `_*.py`, `debug_*.py`, `test_*.py` or ad-hoc scratch files created during development should be deleted. They don't belong in the repo.

2. **Update `.gitignore`** — add patterns for root-level debug scripts if not already present (e.g. `/debug_*.py`, `/_*.py`, `/tmp*.py`).

3. **Check `git status`** — verify only intended files are staged:
   ```
   Modified: src/pytvtools/indicators.py, indicator_parity.py, pine_parity.py
   New:      pine_indicators/<name>.pine, plan/<NN-name>.md (optional)
   ```

4. **Check `git diff --stat`** — make sure no unrelated changes leaked in.

5. **Verify all tests pass** one final time after any cleanup edits.

### 10. Commit and push

```bash
git add -A && git commit -m "feat: add <indicator name> parity (Python + Pine, 100% match)"
git push
```

## Gotchas (Lessons from Previous Sessions)

- **`pine_set_source` returns `{"ok":true}` even when editor is closed.** Always verify the editor panel is open before setting source — otherwise compile silently does nothing.
- **Shorttitle > 10 chars generates a warning** (severity 4). Harmless but noisy; keep shorttitle ≤ 10 chars.
- **`compare_indicator()` does not remove the indicator.** The study stays on the chart after comparison. Always call `remove_all_indicators()` between checks (2-indicator hard limit).
- **Each `TV()` instance has independent auth.** Interactive scripts that create their own `async with TV()` won't share login state with the MCP server.
- **SRSI input IDs are counterintuitive.** `in_0=smooth_k, in_1=smooth_d, in_2=period` — not period first. Always read raw input IDs via `getInputValues()`.
- **BB stddev is `in_3`, not `in_2`.** `in_2` is MA Type, `in_3` is StdDev, `in_4` is Median.
- **`_PLOT_KEY_MAP` plot names are case-sensitive.** TV returns "Upper", "Basis", "Lower" (not "upper", "basis", "lower"). Check exact names from `get_indicator_data()` output.
- **Always load full history before reading indicator data.** `scrollToFirstBar()` + `zoom(-1000)` + 2s sleep. Without this, TV may not compute values for early bars, causing spurious mismatches.
- **Wait up to 7.5s for indicator data.** The framework retries up to 15 times at 0.5s intervals. If it still returns empty, the chart likely didn't load enough history.
- **MCP restart needed after `tv.py` changes.** If running through the MCP server, restart the server (or kill the process) to pick up code edits.
- **Prefer direct Python execution over MCP for development.** Interactive `async with TV()` in Python gives faster iteration and better error visibility.
- **Plan files (`plan/*.md`) are optional** but useful for tracking progress across sessions. Create one per indicator.

## Common Pitfalls

| Problem | Fix |
|---------|------|
| `add_indicator` JS error using short name | Use full TV study ID (`STD;Bollinger_Bands` not `STD;BB`) |
| Mismatches on first bars | Zoom chart to load full history (`scrollToFirstBar` + `zoom(-1000)`) |
| Input IDs don't match order | Read raw IDs from `getInputValues()` |
| Wrong smoothing type | TV's RSI/MFI uses Wilder's (`alpha=1/period`), ATR uses RMA, SRSI uses SMA |
| Multi-plot key mismatch | Check TV plot names in `get_indicator_data()` output vs `_PLOT_KEY_MAP` |
| `pine_compile` returns `{"ok":true}` but no entity | Editor may be closed; open it first with `tv._eval()` to click Pine button |
| Chart has 2-indicator hard limit | Always `remove_all_indicators()` before each `compare_indicator()` call |

## Reference Files

| File | What it contains |
|------|------------------|
| `src/pytvtools/indicators.py` | All Python implementations |
| `src/pytvtools/indicator_parity.py` | `_BUILTIN_COMPUTERS`, `_TV_INPUT_MAP`, `_PLOT_KEY_MAP`, `_STUDY_ID_ALIASES` |
| `src/pytvtools/pine_parity.py` | `_PINE_INDICATORS` registry |
| `pine_indicators/` | Reference Pine Script files |
| `plan/` | Implementation plans for each indicator |
| `tests/test_indicators.py` | Unit tests for Python impls |
| `tests/test_indicator_parity.py` | Unit tests for Python-vs-TV comparison |
| `tests/test_pine_parity.py` | Unit tests for Pine-vs-TV comparison |
