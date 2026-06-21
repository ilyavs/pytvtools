# Stochastic RSI (SRSI)

**TV study ID:** `STD;Stoch_RSI`
**Python function:** `srsi(data, period=14, smooth_k=3, smooth_d=3)`
**Pine file:** `pine_indicators/srsi.pine`

## TV defaults

| Input | ID | Default |
|-------|----|---------|
| Length RSI | `in_0` | 14 |
| Length Stoch | `in_1` | 14 |
| Smooth K | `in_2` | 3 |
| Smooth D | `in_3` | 3 |
| Source | `in_4` | close |

TV computes: `stoch(rsi(src, lengthRSI), rsi(src, lengthRSI), rsi(src, lengthRSI), lengthStoch)` then SMA smooths K.

## Implementation

### Python (`indicators.py`)

```python
def srsi(data, period=14, smooth_k=3, smooth_d=3):
    prices = _prices(data)
    rsi_vals = rsi(prices, period=period)
    stoch_vals = [None] * period
    for i in range(period, len(rsi_vals)):
        if rsi_vals[i] is None:
            stoch_vals.append(None)
            continue
        window = [x for x in rsi_vals[i - period + 1 : i + 1] if x is not None]
        if not window:
            stoch_vals.append(None)
            continue
        low = min(window)
        high = max(window)
        if high == low:
            stoch_vals.append(100.0)
        else:
            stoch_vals.append((rsi_vals[i] - low) / (high - low) * 100)
    k_vals = [None] * (smooth_k - 1) if smooth_k > 0 else []
    if smooth_k > 1:
        for i in range(len(stoch_vals)):
            if i < smooth_k - 1 or stoch_vals[i] is None:
                if i >= len(k_vals):
                    k_vals.append(None)
                continue
            window = stoch_vals[i - smooth_k + 1 : i + 1]
            if any(x is None for x in window):
                k_vals.append(None)
            else:
                k_vals.append(sum(window) / smooth_k)
    else:
        k_vals = list(stoch_vals)
    d_vals = [None] * (smooth_d - 1) if smooth_d > 0 else []
    if smooth_d > 1:
        for i in range(len(k_vals)):
            if i < smooth_d - 1 or k_vals[i] is None:
                if i >= len(d_vals):
                    d_vals.append(None)
                continue
            window = k_vals[i - smooth_d + 1 : i + 1]
            if any(x is None for x in window):
                d_vals.append(None)
            else:
                d_vals.append(sum(window) / smooth_d)
    else:
        d_vals = list(k_vals)
    return [{"k": k, "d": d} for k, d in zip(k_vals, d_vals)]
```

Register in `_BUILTIN_COMPUTERS`:
- `"STD;Stoch_RSI": srsi`

Register in `_TV_INPUT_MAP`:
- `"STD;Stoch_RSI": {"in_0": "period", "in_2": "smooth_k", "in_3": "smooth_d"}`

### Pine (`pine_indicators/srsi.pine`)

```pine
//@version=6
indicator(title="Custom SRSI", shorttitle="SRSI_Custom", format=format.price, precision=2, timeframe="")

len_rsi = input.int(14, "Length RSI")
len_stoch = input.int(14, "Length Stoch")
smooth_k = input.int(3, "Smooth K")
smooth_d = input.int(3, "Smooth D")
src = input.source(close, "Source")

rsi_val = ta.rsi(src, len_rsi)
k = ta.sma(ta.stoch(rsi_val, rsi_val, rsi_val, len_stoch), smooth_k)
d = ta.sma(k, smooth_d)

plot(k, "K", color=color.blue)
plot(d, "D", color=color.orange)
hline(80, "Upper", color=color.gray, linestyle=hline.style_dashed)
hline(20, "Lower", color=color.gray, linestyle=hline.style_dashed)
```

## Registration in `_PINE_INDICATORS`

```python
"srsi": {
    "file": "srsi.pine",
    "study_id": "STD;Stoch_RSI",
    "plot_index": 0,
},
```

## Test plan

1. Python unit test: `test_indicators.py` — verify SRSI output shape
2. Python-vs-TV parity: `compare_indicator(tv, "SPCFD:SPX", "1D", "STD;Stoch_RSI")` — >99% match
3. Pine-vs-TV parity: `compare_pine_indicator(tv, "SPCFD:SPX", "1D", "srsi", use_pine_editor=True)` — >99% match
4. After all pass: commit and push
