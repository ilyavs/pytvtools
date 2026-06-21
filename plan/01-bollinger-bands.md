# Bollinger Bands (BB)

**TV study ID:** `STD;BB`
**Python function:** `bbands(data, period=20, stddev=2.0)`
**Pine file:** `pine_indicators/bbands.pine`

## TV defaults

| Input | ID | Default |
|-------|----|---------|
| Length | `in_0` | 20 |
| Source | `in_1` | close |
| StdDev | `in_2` | 2.0 |
| MA Type | `in_3` | SMA |
| Median | `in_4` | false |

## Implementation

### Python (`indicators.py`)

```python
def bbands(data, period=20, stddev=2.0):
    prices = _prices(data)
    half = period // 2
    result = []
    for i in range(len(prices)):
        if i < period - 1:
            result.append(None)
            continue
        window = prices[i - period + 1 : i + 1]
        ma = sum(window) / period
        variance = sum((x - ma) ** 2 for x in window) / period
        sd = math.sqrt(variance)
        result.append({
            "upper": ma + stddev * sd,
            "basis": ma,
            "lower": ma - stddev * sd,
        })
    return result
```

Register in `_BUILTIN_COMPUTERS`:
- `"STD;BB": bbands`

Register in `_TV_INPUT_MAP`:
- `"STD;BB": {"in_0": "period", "in_2": "stddev"}`

### Pine (`pine_indicators/bbands.pine`)

```pine
//@version=6
indicator(title="Custom BB", shorttitle="BB_Custom", format=format.price, precision=2, timeframe="")

length = input.int(20, "Length")
src = input.source(close, "Source")
mult = input.float(2.0, "StdDev")

basis = ta.sma(src, length)
dev = mult * ta.stdev(src, length)
upper = basis + dev
lower = basis - dev

plot(upper, "Upper", color=color.purple)
plot(basis, "Basis", color=color.blue)
plot(lower, "Lower", color=color.purple)
```

## Registration in `_PINE_INDICATORS`

```python
"bbands": {
    "file": "bbands.pine",
    "study_id": "STD;BB",
    "plot_index": 0,
},
```

## Test plan

1. Python unit test: `test_indicators.py` — verify bbands output shape and values
2. Python-vs-TV parity: `compare_indicator(tv, "SPCFD:SPX", "1D", "STD;BB")` — >99% match
3. Pine-vs-TV parity: `compare_pine_indicator(tv, "SPCFD:SPX", "1D", "bbands", use_pine_editor=True)` — >99% match
4. After all pass: commit and push
