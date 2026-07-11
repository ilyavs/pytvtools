"""Pure-Python implementations of common technical indicators.

All functions accept either a flat list of floats (``close_prices``)
or a list of OHLCV bar dicts with at least a ``"close"`` key.

Multi-column indicators (MACD, BBands, SRSI, SuperTrend, DSS)
require dict bars and return ``dict[str, list]``.

Volume-based indicators (MFI, PVP, etc.) require dict bars with
``"high"``, ``"low"``, ``"close"``, ``"volume"`` and raise
``ValueError`` if given flat floats.

Usage::

    from pytvtools_core.indicators import rsi

    bars = [{"close": 44.34}, {"close": 44.09}]
    closes = [b["close"] for b in bars]
    rsi_vals = rsi(closes, period=14)
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import math
from typing import Any
from pytvtools_core.types import OHLCVBar


def _prices(data: list[float] | list[OHLCVBar]) -> list[float]:
    if not data:
        return []
    if isinstance(data[0], dict):
        return [d["close"] for d in data]  # type: ignore[misc]
    return [float(d) for d in data]  # type: ignore[misc]


def sma(data: list[float] | list[OHLCVBar], period: int = 20) -> list[float | None]:
    """Simple Moving Average.

    Returns a list the same length as *data*; the first ``period - 1``
    values are ``None``.
    """
    prices = _prices(data)
    if len(prices) < period:
        return [None] * len(prices)
    result: list[float | None] = [None] * (period - 1)
    for i in range(period - 1, len(prices)):
        result.append(sum(prices[i - period + 1 : i + 1]) / period)
    return result


def ema(data: list[float] | list[OHLCVBar], period: int = 20) -> list[float | None]:
    """Exponential Moving Average.

    Uses ``alpha = 2 / (period + 1)`` with SMA seed.
    """
    prices = _prices(data)
    if len(prices) < period:
        return [None] * len(prices)

    multiplier = 2.0 / (period + 1)
    result: list[float | None] = [None] * (period - 1)

    seed = sum(prices[:period]) / period
    result.append(seed)

    for i in range(period, len(prices)):
        result.append((prices[i] - result[-1]) * multiplier + result[-1])
    return result


def rsi(data: list[float] | list[OHLCVBar], period: int = 14) -> list[float | None]:
    """Relative Strength Index (Wilder's smoothing).

    Uses ``alpha = 1 / period`` for average gain/loss.
    """
    prices = _prices(data)
    if len(prices) < period + 1:
        return [None] * len(prices)

    result: list[float | None] = [None] * period

    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, period + 1):
        diff = prices[i] - prices[i - 1]
        gains.append(diff if diff > 0 else 0.0)
        losses.append(-diff if diff < 0 else 0.0)

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        result.append(100.0)
    else:
        rs = avg_gain / avg_loss
        result.append(100.0 - 100.0 / (1.0 + rs))

    for i in range(period + 1, len(prices)):
        diff = prices[i] - prices[i - 1]
        gain = diff if diff > 0 else 0.0
        loss = -diff if diff < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            result.append(100.0)
        else:
            rs = avg_gain / avg_loss
            result.append(100.0 - 100.0 / (1.0 + rs))

    return result


def mfi(data: list[float] | list[OHLCVBar], period: int = 14) -> list[float | None]:
    """Money Flow Index (SMA-based rolling sum).

    Requires OHLCV bar dicts with ``"high"``, ``"low"``, ``"close"``, ``"volume"`` keys.
    Raises ``ValueError`` if given a flat list of floats (no volume data).

    Uses a rolling sum of positive/negative money flow over *period* bars.
    """
    if not data:
        return []

    if isinstance(data[0], dict):
        highs = [float(d["high"]) for d in data]  # type: ignore[misc]
        lows = [float(d["low"]) for d in data]  # type: ignore[misc]
        closes = [float(d["close"]) for d in data]  # type: ignore[misc]
        volumes = [float(d["volume"]) for d in data]  # type: ignore[misc]
    else:
        raise ValueError(
            "mfi() requires OHLCV bar dicts with 'high', 'low', 'close', "
            "'volume' keys. A flat list of closes is not sufficient."
        )

    n = len(closes)
    if n < period + 1:
        return [None] * n

    tp = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(n)]

    result: list[float | None] = [None] * period

    pos: list[float] = [0.0]
    neg: list[float] = [0.0]
    for i in range(1, n):
        mf = tp[i] * volumes[i]
        if tp[i] > tp[i - 1]:
            pos.append(mf)
            neg.append(0.0)
        elif tp[i] < tp[i - 1]:
            pos.append(0.0)
            neg.append(mf)
        else:
            pos.append(0.0)
            neg.append(0.0)

    for i in range(period, n):
        sum_pos = sum(pos[i - period + 1 : i + 1])
        sum_neg = sum(neg[i - period + 1 : i + 1])
        if sum_neg == 0.0:
            result.append(100.0)
        elif sum_pos == 0.0:
            result.append(0.0)
        else:
            mr = sum_pos / sum_neg
            result.append(100.0 - 100.0 / (1.0 + mr))

    return result


def _auto_tick_size(prices: list[float]) -> float:
    """Auto-detect a reasonable tick size from price levels.
    """
    if not prices:
        return 1.0
    avg = sum(prices) / len(prices)
    if avg < 0.01:
        return 0.00001
    if avg < 0.1:
        return 0.0001
    if avg < 1:
        return 0.001
    if avg < 10:
        return 0.01
    if avg < 100:
        return 0.05
    if avg < 1000:
        return 0.5
    if avg < 10000:
        return 1.0
    if avg < 100000:
        return 5.0
    return 10.0


def macd(
    data: list[float] | list[OHLCVBar],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> dict[str, list[float | None]]:
    """MACD indicator.

    Returns ``{"macd": ..., "signal": ..., "histogram": ...}``, each a
    list aligned to the input length.
    """
    prices = _prices(data)
    fast_ema = ema(prices, fast)
    slow_ema = ema(prices, slow)

    macd_line: list[float | None] = [None] * len(prices)
    for i in range(len(prices)):
        if fast_ema[i] is not None and slow_ema[i] is not None:
            macd_line[i] = fast_ema[i] - slow_ema[i]  # type: ignore[operator]

    signal_line = ema([v for v in macd_line if v is not None], signal)  # type: ignore[arg-type]
    signal_padded: list[float | None] = [None] * len(prices)

    valid_idx = 0
    for i in range(len(prices)):
        if macd_line[i] is not None:
            if valid_idx < len(signal_line):
                signal_padded[i] = signal_line[valid_idx]
            valid_idx += 1

    histogram: list[float | None] = [None] * len(prices)
    for i in range(len(prices)):
        if macd_line[i] is not None and signal_padded[i] is not None:
            histogram[i] = macd_line[i] - signal_padded[i]

    return {"macd": macd_line, "signal": signal_padded, "histogram": histogram}


def bbands(
    data: list[float] | list[OHLCVBar],
    period: int = 20,
    stddev: float = 2.0,
) -> dict[str, list[float | None]]:
    """Bollinger Bands.

    Returns ``{"upper": ..., "basis": ..., "lower": ...}``, each a
    list aligned to the input length.
    """
    prices = _prices(data)
    upper: list[float | None] = [None] * len(prices)
    basis: list[float | None] = [None] * len(prices)
    lower: list[float | None] = [None] * len(prices)

    for i in range(len(prices)):
        if i < period - 1:
            continue
        window = prices[i - period + 1 : i + 1]
        ma = sum(window) / period
        variance = sum((x - ma) ** 2 for x in window) / period
        sd = variance ** 0.5
        basis[i] = ma
        upper[i] = ma + stddev * sd
        lower[i] = ma - stddev * sd

    return {"upper": upper, "basis": basis, "lower": lower}


def srsi(
    data: list[float] | list[OHLCVBar],
    period: int = 14,
    smooth_k: int = 3,
    smooth_d: int = 3,
) -> dict[str, list[float | None]]:
    """Stochastic RSI.

    Returns ``{"k": ..., "d": ...}``, each a list aligned to the input length.
    """
    prices = _prices(data)
    rsi_vals = rsi(prices, period=period)

    raw_k: list[float | None] = [None] * len(prices)
    for i in range(len(prices)):
        if rsi_vals[i] is None:
            continue
        start = max(0, i - period + 1)
        window = [rsi_vals[j] for j in range(start, i + 1) if rsi_vals[j] is not None]
        if len(window) < 2:
            continue
        low = min(window)
        high = max(window)
        if high == low:
            raw_k[i] = 100.0
        else:
            raw_k[i] = (rsi_vals[i] - low) / (high - low) * 100

    k = sma_series(raw_k, smooth_k) if smooth_k > 0 else raw_k
    d = sma_series(k, smooth_d) if smooth_d > 0 else k

    return {"k": k, "d": d}


def sma_series(values: list[float | None], period: int) -> list[float | None]:
    """Apply SMA smoothing to a series that may have leading None values."""
    valid = [v for v in values if v is not None]
    if not valid:
        return values
    smoothed = sma(valid, period)
    result: list[float | None] = [None] * len(values)
    idx = 0
    for i in range(len(values)):
        if values[i] is not None:
            if idx < len(smoothed):
                result[i] = smoothed[idx]
            idx += 1
    return result


def supertrend(
    data: list[float] | list[OHLCVBar],
    period: int = 10,
    multiplier: float = 3.0,
) -> dict[str, list[float | None]]:
    """SuperTrend indicator.

    Returns ``{"up_trend": ..., "down_trend": ...}``, each a list aligned
    to the input length.  Only one plot has a non-None value at any bar.

    TV direction convention: -1 = uptrend (green), 1 = downtrend (red).

    Requires OHLCV dict bars.  Raises ``ValueError`` if given flat floats.
    """
    if not data:
        return {"up_trend": [], "down_trend": []}
    if not isinstance(data[0], dict):
        raise ValueError("SuperTrend requires OHLCV dict bars")

    highs = [float(d["high"]) for d in data]  # type: ignore[misc]
    lows = [float(d["low"]) for d in data]  # type: ignore[misc]
    closes = [float(d["close"]) for d in data]  # type: ignore[misc]

    n = len(data)
    up_trend: list[float | None] = [None] * n
    down_trend: list[float | None] = [None] * n

    if n < period + 1:
        return {"up_trend": up_trend, "down_trend": down_trend}

    # Compute ATR matching TV's ta.supertrend() internal ATR, NOT ta.atr().
    # TV's supertrend uses tr[0]=high[0]-low[0] in the SMA seed, giving the first
    # value at bar period-1.  The standalone ta.atr() uses a different seed (no
    # tr[0]), giving the first value at bar period.  These are NOT the same — the
    # inline code is intentional, not a violation of the reuse rule.
    tr: list[float] = [highs[0] - lows[0]]
    for i in range(1, n):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr.append(max(hl, hc, lc))

    atr_vals: list[float | None] = [None] * n
    rma = sum(tr[:period]) / period
    atr_vals[period - 1] = rma
    for i in range(period, n):
        rma = (rma * (period - 1) + tr[i]) / period
        atr_vals[i] = rma

    hl2 = [(highs[i] + lows[i]) / 2.0 for i in range(n)]

    prev_lower = 0.0
    prev_upper = 0.0
    prev_super = 0.0

    for i in range(period - 1, n):
        if atr_vals[i] is None:
            continue

        basic_lower = hl2[i] - multiplier * atr_vals[i]
        basic_upper = hl2[i] + multiplier * atr_vals[i]

        if i == period - 1:
            ratcheted_lower = basic_lower
            ratcheted_upper = basic_upper
            direction = 1 if closes[i] < ratcheted_lower else -1
        else:
            prev_close = closes[i - 1]
            ratcheted_lower = basic_lower if (basic_lower > prev_lower or prev_close < prev_lower) else prev_lower
            ratcheted_upper = basic_upper if (basic_upper < prev_upper or prev_close > prev_upper) else prev_upper
            if prev_super == prev_upper:
                direction = 1 if closes[i] < ratcheted_lower else -1
            else:
                direction = -1 if closes[i] > ratcheted_upper else 1

        super_value = ratcheted_lower if direction == -1 else ratcheted_upper

        if direction == -1:
            up_trend[i] = super_value
        else:
            down_trend[i] = super_value

        prev_lower = ratcheted_lower
        prev_upper = ratcheted_upper
        prev_super = super_value

    return {"up_trend": up_trend, "down_trend": down_trend}


def ema_series(values: list[float | None], period: int) -> list[float | None]:
    """Apply EMA smoothing to a series that may have leading None values."""
    valid = [v for v in values if v is not None]
    if not valid:
        return values
    smoothed = ema(valid, period)
    result: list[float | None] = [None] * len(values)
    idx = 0
    for i in range(len(values)):
        if values[i] is not None:
            if idx < len(smoothed):
                result[i] = smoothed[idx]
            idx += 1
    return result


def dss(
    data: list[float] | list[OHLCVBar],
    pds: int = 10,
    ema_len: int = 9,
    trigger_len: int = 5,
) -> dict[str, list[float | None]]:
    """Double Smoothed Stochastic (DSS Bressert) by HPotter.
      ``[c,h,l] = security(ticker, res, [close,high,low])``
      ``xPreCalc = ema(stoch(c,h,l,PDS), EMAlen)``
      ``xDSS = ema(stoch(xPreCalc,xPreCalc,xPreCalc,PDS), EMAlen)``
      ``xTrigger = ema(xDSS, TriggerLen)``

    When ``resampled`` is True (default), the function expects *hourly*
    (60-min) OHLCV bars and extracts the last hourly bar per day so that
    the stochastic inputs match what ``security(syminfo.tickerid, "60",
    [close,high,low])`` would return on a daily chart.

    Set ``resampled=False`` to use daily OHLCV directly (faster but less
    accurate parity with the default ``res="60"`` setting).

    Returns ``{"dss": ..., "trigger": ...}``, each a list aligned to the
    input length.

    Requires OHLCV dict bars.  Raises ``ValueError`` if given flat floats.
    """
    if not data:
        return {"dss": [], "trigger": []}
    if not isinstance(data[0], dict):
        raise ValueError(
            "dss() requires OHLCV bar dicts with 'high', 'low', 'close' keys. "
            "A flat list of closes is not sufficient."
        )

    n = len(data)

    # Extract OHLCV — if bars have a 'resampled_close' key use that,
    # otherwise read the standard fields (daily OHLCV).
    if "resampled_close" in data[0]:
        closes = [float(d["resampled_close"]) for d in data]  # type: ignore[misc]
        highs = [float(d["resampled_high"]) for d in data]  # type: ignore[misc]
        lows = [float(d["resampled_low"]) for d in data]  # type: ignore[misc]
    else:
        closes = [float(d["close"]) for d in data]  # type: ignore[misc]
        highs = [float(d["high"]) for d in data]  # type: ignore[misc]
        lows = [float(d["low"]) for d in data]  # type: ignore[misc]

    # Step 1: stoch(close, high, low, pds)
    stoch1: list[float | None] = [None] * n
    for i in range(pds - 1, n):
        hh = max(highs[i - pds + 1 : i + 1])
        ll = min(lows[i - pds + 1 : i + 1])
        if hh == ll:
            stoch1[i] = 50.0
        else:
            stoch1[i] = 100.0 * (closes[i] - ll) / (hh - ll)

    # Step 2: ema of stoch1 with ema_len → xPreCalc
    x_pre_calc = ema_series(stoch1, ema_len)

    # Step 3: stoch(xPreCalc, xPreCalc, xPreCalc, pds) → stoch2
    stoch2: list[float | None] = [None] * n
    for i in range(pds - 1, n):
        window = [x_pre_calc[j] for j in range(i - pds + 1, i + 1)]
        clean = [v for v in window if v is not None]
        if len(clean) < pds:
            continue
        hh = max(clean)
        ll = min(clean)
        val = x_pre_calc[i]
        if val is None:
            continue
        if hh == ll:
            stoch2[i] = 50.0
        else:
            stoch2[i] = 100.0 * (val - ll) / (hh - ll)

    # Step 3b: ema of stoch2 with ema_len → xDSS  (2nd EMA — matches active
    #           line in PUB;85 source, not the commented-out variant)
    dss_line = ema_series(stoch2, ema_len)

    # Step 4: ema of DSS with trigger_len → Trigger
    trigger = ema_series(dss_line, trigger_len)

    return {"dss": dss_line, "trigger": trigger}


def market_cipher_b(
    data: list[float] | list[OHLCVBar],
    channel_length: int = 10,
    average_length: int = 21,
) -> dict[str, list[float | None]]:
    """Market Cipher B WaveTrend oscillator.

    Based on LazyBear's WaveTrend and falconcoin's Market Cipher B free version.
    Uses HLC3 as the source and computes two WaveTrend lines (WT1, WT2)
    via sequential EMA and SMA smoothing.

    Requires OHLCV dict bars.  Raises ``ValueError`` if given flat floats.

    Returns ``{"wt1": ..., "wt2": ..., "wt1_minus_wt2": ...}``.
    """
    if not data:
        return {"wt1": [], "wt2": [], "wt1_minus_wt2": []}
    if not isinstance(data[0], dict):
        raise ValueError("market_cipher_b requires OHLCV dict bars")

    highs = [float(d["high"]) for d in data]  # type: ignore[misc]
    lows = [float(d["low"]) for d in data]  # type: ignore[misc]
    closes = [float(d["close"]) for d in data]  # type: ignore[misc]
    n = len(data)

    ap = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(n)]

    esa_vals = ema(ap, channel_length)

    diff: list[float | None] = [None] * n
    for i in range(n):
        if esa_vals[i] is not None:
            diff[i] = abs(ap[i] - esa_vals[i])

    d_vals = ema_series(diff, channel_length)

    ci: list[float | None] = [None] * n
    for i in range(n):
        if esa_vals[i] is not None and d_vals[i] is not None and d_vals[i] != 0:
            ci[i] = (ap[i] - esa_vals[i]) / (0.015 * d_vals[i])

    wt1 = ema_series(ci, average_length)
    wt2 = sma_series(wt1, 4)

    wt1_minus_wt2: list[float | None] = [None] * n
    for i in range(n):
        if wt1[i] is not None and wt2[i] is not None:
            wt1_minus_wt2[i] = wt1[i] - wt2[i]

    return {"wt1": wt1, "wt2": wt2, "wt1_minus_wt2": wt1_minus_wt2}


def atr(
    data: list[float] | list[OHLCVBar],
    period: int = 14,
) -> list[float | None]:
    """Average True Range (ATR) with Wilder's smoothing (RMA).

    Requires OHLCV dict bars.  Raises ``ValueError`` if given flat floats.
    """
    if not data:
        return []
    if not isinstance(data[0], dict):
        raise ValueError("ATR requires OHLCV dict bars")
    highs = [float(d["high"]) for d in data]  # type: ignore[misc]
    lows = [float(d["low"]) for d in data]  # type: ignore[misc]
    closes = [float(d["close"]) for d in data]  # type: ignore[misc]

    tr: list[float | None] = [None] * len(data)
    for i in range(1, len(data)):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr[i] = max(hl, hc, lc)

    result: list[float | None] = [None] * len(data)

    if period <= 1:
        return result

    rma = sum(tr[1 : period + 1]) / period  # type: ignore[arg-type]
    result[period] = rma

    for i in range(period + 1, len(tr)):
        if tr[i] is not None:
            rma = (rma * (period - 1) + tr[i]) / period
            result[i] = rma

    return result


_STANDARD_TICKS = [1.0, 0.5, 0.2, 0.1, 0.05, 0.02, 0.01, 0.005, 0.002, 0.001, 0.0005, 0.0002, 0.0001]


def _infer_mintick(data: list[OHLCVBar], max_samples: int = 200) -> float:
    """Infer minimum tick size from price data.

    Looks at prices in the first *max_samples* bars and finds the
    smallest non-zero difference between adjacent price levels.
    The result is rounded to the nearest standard tick size to
    eliminate sub-tick noise in bar data.
    """
    prices: set[float] = set()
    for b in data[:max_samples]:
        prices.add(round(float(b["high"]), 10))
        prices.add(round(float(b["low"]), 10))
    sorted_prices = sorted(prices)
    if len(sorted_prices) < 2:
        return 0.01
    diffs = [
        round(sorted_prices[i + 1] - sorted_prices[i], 10)
        for i in range(len(sorted_prices) - 1)
        if round(sorted_prices[i + 1] - sorted_prices[i], 10) > 1e-10
    ]
    if not diffs:
        return 0.01
    min_diff = min(diffs)
    return min(_STANDARD_TICKS, key=lambda t: abs(t - min_diff))


def pvp(
    data: list[float] | list[OHLCVBar],
    period_mult: int = 1,
    period_unit: str = "Day",
    num_rows: int = 24,
    mintick: float | None = None,
    utc_offset: float | None = None,
) -> list[float | None]:
    """Periodic Volume Profile — POC at period boundaries.

    Replicates the exact tick-based row-sizing algorithm from
    ``pvp.pine``'s ``f_poc()`` function.

    Parameters
    ----------
    data : list[dict]
        OHLCV bars with ``'high'``, ``'low'``, ``'volume'``, ``'timestamp'``.
    period_mult : int
        Period multiplier (1, 2, …).
    period_unit : str
        ``"Day"`` (default), ``"Week"``, or ``"Month"``.
    num_rows : int
        Target number of rows for the volume histogram (default 24).
    mintick : float, optional
        Minimum price tick.  Auto-inferred from data if omitted.
    utc_offset : float, optional
        Hours from UTC (e.g. -5 for US Eastern Standard Time).
        Shifts period boundaries to match the exchange timezone.
        ``None`` (default) uses UTC midnight boundaries.

    Returns
    -------
    ``list[float | None]`` aligned to the input length.  Values are
    ``None`` for bars that are not the last bar of a period.
    """
    if not data:
        return []

    if not isinstance(data[0], dict):
        raise ValueError(
            "pvp() requires OHLCV bar dicts with 'high', 'low', 'volume', "
            "'timestamp' keys."
        )

    n = len(data)

    if mintick is None:
        mintick = _infer_mintick(data)  # type: ignore[arg-type]
    if mintick <= 0:
        mintick = 0.01

    exchange_midnight_offset = int((-utc_offset) * 3600) if utc_offset is not None else 0

    first_ts = int(data[0]["timestamp"])  # type: ignore[arg-type]
    ts_div = 1000 if first_ts > 1e11 else 1

    def _period_key(ts_seconds: int) -> tuple[int, int]:
        shifted_ts = ts_seconds - exchange_midnight_offset
        dt = datetime.fromtimestamp(shifted_ts, tz=timezone.utc)
        if period_unit == "Day":
            base = (shifted_ts // 86400) * 86400
        elif period_unit == "Week":
            days_since_monday = dt.weekday()
            week_start = dt - timedelta(days=days_since_monday)
            week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
            base = int(week_start.timestamp())
        elif period_unit == "Month":
            month_start = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            base = int(month_start.timestamp())
        else:
            base = (shifted_ts // 86400) * 86400
        if period_mult > 1:
            periods_since_epoch = base // 86400
            period_remainder = periods_since_epoch % period_mult
            base -= period_remainder * 86400
        period_key = base + exchange_midnight_offset
        # Year alignment: profiles start fresh at each calendar year boundary,
        # matching Pine's `year_change = ta.change(time("12M"))` logic.
        year_start = dt.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        year_key = int(year_start.timestamp()) + exchange_midnight_offset
        return (year_key, period_key)

    period_groups: dict[tuple[int, int], list[int]] = {}
    for i in range(n):
        ts = int(data[i]["timestamp"]) // ts_div  # type: ignore[arg-type]
        pk = _period_key(ts)
        if pk not in period_groups:
            period_groups[pk] = []
        period_groups[pk].append(i)

    result: list[float | None] = [None] * n

    for indices in period_groups.values():
        if not indices:
            continue

        period_bars = [data[i] for i in indices]  # type: ignore[arg-type]

        poc_price = _compute_period_poc(
            [float(b["high"]) for b in period_bars],  # type: ignore[arg-type]
            [float(b["low"]) for b in period_bars],
            [float(b.get("volume", 0) or 0) for b in period_bars],
            num_rows=num_rows,
            mintick=mintick,
        )
        if poc_price is not None:
            result[indices[-1]] = poc_price

    return result


def _compute_period_poc(
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    num_rows: int,
    mintick: float,
) -> float | None:
    """Compute POC for a single period's bars.

    Replicates ``pvp.pine``'s ``f_poc()`` algorithm exactly.
    """
    min_p = min(lows)
    max_p = max(highs)
    pr = max_p - min_p

    if pr <= 0 or mintick <= 0:
        return None

    ticks = pr / mintick

    tpr_down = int(math.floor(ticks / num_rows))
    tpr_down = max(tpr_down, 1)
    tpr_up = int(math.ceil(ticks / num_rows))
    tpr_up = max(tpr_up, 1)

    rows_down = int(math.ceil(ticks / tpr_down))
    rows_up = int(math.ceil(ticks / tpr_up))

    tpr_used = tpr_down if abs(rows_down - num_rows) <= abs(rows_up - num_rows) else tpr_up
    total_rows = int(math.ceil(ticks / tpr_used))
    row_height = tpr_used * mintick

    row_volumes = [0.0] * total_rows

    for i in range(len(lows)):
        bv = volumes[i]
        if bv <= 0:
            continue
        bh = highs[i]
        bl = lows[i]
        tr = (bh - bl) / mintick
        nt = max(int(tr), 1)
        n_levels = nt + 1
        vpt = bv / n_levels

        for t in range(nt + 1):
            price = bl + t * mintick
            r = int((price - min_p) / row_height)
            r = max(0, min(total_rows - 1, r))
            row_volumes[r] += vpt

    max_vol = max(row_volumes)
    if max_vol <= 0:
        return None

    poc_row = row_volumes.index(max_vol)
    return min_p + (poc_row + 0.5) * row_height
