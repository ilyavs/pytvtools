"""Pure-Python implementations of common technical indicators.

All functions accept either a flat list of floats (``close_prices``)
or a list of OHLCV bar dicts with at least a ``"close"`` key.

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

    alpha = 1.0 / period
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
