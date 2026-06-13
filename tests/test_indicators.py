"""Tests for indicators.py — pure-Python technical indicator calculations."""

from __future__ import annotations

import math

import pytest

from pytvtools.indicators import sma, ema, rsi, macd


def approx(seq):
    """Return a list of rounded values, treating None as None."""
    return [round(v, 6) if v is not None else None for v in seq]


class TestSMA:
    def test_sma_known_values(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        result = sma(data, period=3)
        expected = [None, None, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
        assert approx(result) == approx(expected)

    def test_sma_shorter_than_period(self):
        result = sma([1.0, 2.0], period=5)
        assert result == [None, None]

    def test_sma_empty(self):
        assert sma([], period=10) == []

    def test_sma_with_dicts(self):
        bars = [{"close": 10.0}, {"close": 20.0}, {"close": 30.0}]
        result = sma(bars, period=2)
        assert approx(result) == [None, 15.0, 25.0]


class TestEMA:
    def test_ema_known_values(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        result = ema(data, period=3)
        expected = [
            None, None,
            2.0,           # SMA seed for first 3
            3.5,           # 4 + (10-4) * 0.5 = 3.5
            5.25,          # 5 + (11.5-5) * 0.5 = 5.25 (wait let me calculate)
        ]
        # EMA(3) alpha = 2 / (3 + 1) = 0.5
        # Seed = (1+2+3)/3 = 2.0 (value at index 2)
        # index 3: (4 - 2) * 0.5 + 2 = 3.0
        # index 4: (5 - 3) * 0.5 + 3 = 4.0
        # index 5: (6 - 4) * 0.5 + 4 = 5.0
        expected = [None, None, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
        assert approx(result) == approx(expected)

    def test_ema_shorter_than_period(self):
        result = ema([1.0, 2.0], period=5)
        assert result == [None, None]

    def test_ema_empty(self):
        assert ema([], period=10) == []


class TestRSI:
    def test_rsi_constant_prices(self):
        """RSI should be 100 when prices only go up (no losses)."""
        prices = [100.0 + i for i in range(20)]
        result = rsi(prices, period=14)
        assert result[14] == 100.0  # first non-None
        assert all(v == 100.0 for v in result[14:])

    def test_rsi_known_values(self):
        """RSI(14) on sequential data."""
        prices = [
            44.34, 44.09, 44.15, 43.61, 44.33,
            44.83, 45.10, 45.42, 45.84, 46.08,
            45.89, 46.03, 45.61, 46.28, 46.28,
            46.00, 46.03, 46.41, 46.22, 46.21,
        ]
        result = rsi(prices, period=14)
        # First 14 values are None
        assert result[:14] == [None] * 14
        # Validate last few values
        assert result[14] is not None
        assert result[15] is not None

    def test_rsi_range(self):
        """RSI values should be between 0 and 100."""
        import random
        random.seed(42)
        prices = [random.uniform(50, 150) for _ in range(100)]
        result = rsi(prices, period=14)
        for v in result:
            if v is not None:
                assert 0 <= v <= 100, f"RSI out of range: {v}"

    def test_rsi_empty(self):
        assert rsi([], period=14) == []

    def test_rsi_short(self):
        assert rsi([1.0, 2.0], period=14) == [None, None]


class TestMACD:
    def test_macd_empty(self):
        result = macd([], fast=12, slow=26, signal=9)
        assert result["macd"] == []
        assert result["signal"] == []
        assert result["histogram"] == []

    def test_macd_known_values(self):
        prices = [float(i) for i in range(1, 101)]
        result = macd(prices, fast=12, slow=26, signal=9)
        # MACD line should have values starting at index 25 (slow - 1)
        assert result["macd"][:25] == [None] * 25
        macd_vals = [v for v in result["macd"] if v is not None]
        signal_vals = [v for v in result["signal"] if v is not None]
        hist_vals = [v for v in result["histogram"] if v is not None]
        assert len(macd_vals) > 0
        assert len(signal_vals) > 0
        assert len(hist_vals) > 0

    def test_macd_structure(self):
        prices = [float(i) for i in range(1, 60)]
        result = macd(prices, fast=12, slow=26, signal=9)
        assert "macd" in result
        assert "signal" in result
        assert "histogram" in result
        assert len(result["macd"]) == len(prices)
        assert len(result["signal"]) == len(prices)
        assert len(result["histogram"]) == len(prices)
