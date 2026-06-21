# Average True Range (ATR)

**TV study ID:** `STD;Average_True_Range`
**Python function:** `atr(data, period=14)`
**Pine file:** `pine_indicators/atr.pine`

## TV defaults

| Input | ID | Default |
|-------|----|---------|
| Length | `in_0` | 14 |
| MA Type | `in_1` | RMA (Wilder's) |

TV uses RMA (Wilder's moving average) for ATR.

## Implementation

### Python (`indicators.py`)

```python
def _wilder_rma(values, period):
    """Wilder's smoothed moving average (RMA)."""
    result = [None] * (period - 1)
    avg = sum(values[:period]) / period
    result.append(avg)
    for v in values[period:]:
        avg = (avg * (period - 1) + v) / period
        result.append(avg)
    return result

def atr(data, period=14):
    if not data:
        return []
    if isinstance(data[0], dict):
        highs = [d["high"] for d in data]
        lows = [d["low"] for d in data]
        closes = [d["close"] for d in data]
    else:
        raise ValueError("ATR requires OHLCV dict bars")
    trs = [None]
    for i in range(1, len(data)):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        trs.append(max(hl, hc, lc))
    # RMA of TR
    rma_vals = _wilder_rma([t for t in trs if t is not None], period)
    result = [None]
    result.extend(rma_vals)
    return result
```

Register in `_BUILTIN_COMPUTERS`:
- `"STD;ATR": atr`

Register in `_TV_INPUT_MAP`:
- `"STD;ATR": {"in_0": "period"}`

### Pine (`pine_indicators/atr.pine`)

```pine
//@version=6
indicator(title="Custom ATR", shorttitle="ATR_Custom", format=format.price, precision=2, timeframe="")

length = input.int(14, "Length")

plot(ta.atr(length), "ATR", color=color.purple)
```

## Registration in `_PINE_INDICATORS`

```python
"atr": {
    "file": "atr.pine",
    "study_id": "STD;ATR",
    "plot_index": 0,
},
```

## Test plan

1. Python unit test: `test_indicators.py` — verify ATR values against known example
2. Python-vs-TV parity: `compare_indicator(tv, "SPCFD:SPX", "1D", "STD;ATR")` — >99% match
3. Pine-vs-TV parity: `compare_pine_indicator(tv, "SPCFD:SPX", "1D", "atr", use_pine_editor=True)` — >99% match
4. After all pass: commit and push
