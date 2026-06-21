"""Pure-Python implementations of common technical indicators.

All functions accept either a flat list of floats (``close_prices``)
or a list of OHLCV bar dicts with at least a ``"close"`` key.

Volume-based indicators (MFI, etc.) require dict bars with
``"high"``, ``"low"``, ``"close"``, ``"volume"`` and raise
``ValueError`` if given flat floats.

Usage::

    from pytvtools.indicators import rsi

    bars = await tv.get_ohlcv(count=500, summary=False)
    closes = [b["close"] for b in bars]
    rsi_vals = rsi(closes, period=14)
"""

from __future__ import annotations

from typing import Any


def _prices(data: list[float] | list[dict[str, Any]]) -> list[float]:
    if not data:
        return []
    if isinstance(data[0], dict):
        return [d["close"] for d in data]  # type: ignore[arg-type]
    return [float(d) for d in data]  # type: ignore[misc]


def sma(data: list[float] | list[dict[str, Any]], period: int = 20) -> list[float | None]:
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


def ema(data: list[float] | list[dict[str, Any]], period: int = 20) -> list[float | None]:
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


def rsi(data: list[float] | list[dict[str, Any]], period: int = 14) -> list[float | None]:
    """Relative Strength Index (Wilder's smoothing).

    Uses ``alpha = 1 / period`` for average gain/loss, matching
    TradingView's built-in RSI.
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


def mfi(data: list[float] | list[dict[str, Any]], period: int = 14) -> list[float | None]:
    """Money Flow Index (SMA-based rolling sum).

    Requires OHLCV bar dicts with ``"high"``, ``"low"``, ``"close"``, ``"volume"`` keys.
    Raises ``ValueError`` if given a flat list of floats (no volume data).

    Uses a rolling sum of positive/negative money flow over *period* bars
    (SMA-equivalent), matching TradingView's built-in MFI.
    """
    if not data:
        return []

    if isinstance(data[0], dict):
        highs = [float(d["high"]) for d in data]
        lows = [float(d["low"]) for d in data]
        closes = [float(d["close"]) for d in data]
        volumes = [float(d["volume"]) for d in data]
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

    Returns the tick increment that is standard for the given price
    range (mimics TradingView's symbol-aware tick sizing).
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


def _pvp_period(
    bars: list[dict[str, Any]],
    rows: int,
    tick_size: float,
) -> dict | None:
    """Compute POC for a single period's bars.

    Returns ``{"poc": float, "start_ts": int, "end_ts": int}``
    or ``None`` when no volume exists.
    """
    lows = [float(b["low"]) for b in bars]
    highs = [float(b["high"]) for b in bars]
    min_price = min(lows)
    max_price = max(highs)
    start_ts = int(bars[0]["timestamp"])
    end_ts = int(bars[-1]["timestamp"])

    if max_price == min_price:
        return {"poc": min_price, "start_ts": start_ts, "end_ts": end_ts}

    price_range = max_price - min_price
    raw_row_size = price_range / rows
    row_size = round(raw_row_size / tick_size) * tick_size
    if row_size == 0:
        row_size = tick_size

    actual_rows = int(price_range / row_size) + 1
    row_volumes = [0.0] * actual_rows

    for bar in bars:
        bar_low = float(bar["low"])
        bar_high = float(bar["high"])
        volume = float(bar["volume"])

        start_row = max(0, min(actual_rows - 1, int((bar_low - min_price) / row_size)))
        end_row = max(0, min(actual_rows - 1, int((bar_high - min_price - 1e-9) / row_size)))

        num_spanned = end_row - start_row + 1
        vol_per_row = volume / num_spanned

        for r in range(start_row, end_row + 1):
            row_volumes[r] += vol_per_row

    max_vol = max(row_volumes)
    if max_vol == 0:
        return None

    poc_row = row_volumes.index(max_vol)
    poc = min_price + (poc_row + 0.5) * row_size

    return {"poc": poc, "start_ts": start_ts, "end_ts": end_ts}


def pvp(
    data: list[dict[str, Any]],
    window: str = "day",
    rows: int = 24,
) -> list[dict]:
    """Periodic Volume Profile — Point of Control per period.

    Groups bars by *window* (``"day"``, ``"week"``, ``"month"``) with
    automatic year-boundary resets, divides each period's price range
    into *rows* tick-aligned buckets, distributes volume across spanned
    rows, and returns the POC for each period with crossing detection.

    Tick size is auto-detected from the price level to match
    TradingView-like behaviour.

    Returns a list of dicts sorted chronologically, one per period::

        {"poc": float, "start_ts": int, "end_ts": int, "crossed_ts": int | None}

    ``crossed_ts`` is the timestamp of the first *subsequent* bar (any
    future period) whose body crosses the POC level (open above & close
    below, or open below & close above).  ``None`` if not crossed within
    the data.

    Requires dict bars with ``"high"``, ``"low"``, ``"close"``,
    ``"volume"``, ``"timestamp"`` keys.
    """
    if not data:
        return []

    if not isinstance(data[0], dict):
        raise ValueError(
            "pvp() requires OHLCV bar dicts with 'high', 'low', 'close', "
            "'volume', 'timestamp' keys. A flat list of closes is not sufficient."
        )

    from datetime import datetime, timezone
    from collections import OrderedDict

    # Auto-detect tick size
    all_prices: list[float] = []
    for bar in data:
        all_prices.append(float(bar["high"]))
        all_prices.append(float(bar["low"]))
    tick_size = _auto_tick_size(all_prices)

    def _period_key(ts: int) -> tuple:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        if window == "day":
            return (dt.year, dt.month, dt.day)
        if window == "week":
            yr, wk, _ = dt.isocalendar()
            return (yr, wk)
        if window == "month":
            return (dt.year, dt.month)
        raise ValueError(f"Unknown window: {window!r} (use 'day', 'week', or 'month')")

    groups: OrderedDict[tuple, list[dict]] = OrderedDict()
    for bar in data:
        key = _period_key(int(bar["timestamp"]))
        groups.setdefault(key, []).append(bar)

    periods: list[dict] = []
    for key, bars in groups.items():
        result = _pvp_period(bars, rows, tick_size)
        if result is not None:
            periods.append(result)

    for period in periods:
        poc = period["poc"]
        end_ts = period["end_ts"]
        crossed: int | None = None
        for bar in data:
            ts = int(bar["timestamp"])
            if ts <= end_ts:
                continue
            o = float(bar.get("open", 0))
            c = float(bar["close"])
            if (o > poc > c) or (o < poc < c):
                crossed = ts
                break
        period["crossed_ts"] = crossed

    return periods


def macd(
    data: list[float] | list[dict[str, Any]],
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
    data: list[float] | list[dict[str, Any]],
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
