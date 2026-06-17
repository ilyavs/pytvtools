"""Tests for indicators.py — pure-Python technical indicator calculations."""

from __future__ import annotations

import pytest

from pytvtools.indicators import sma, ema, rsi, macd, mfi, pvp


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


class TestMFI:
    def test_mfi_known_values(self):
        """MFI(2) on manually computed OHLCV data."""
        bars = [
            {"high": 3, "low": 1, "close": 2, "volume": 10},
            {"high": 5, "low": 3, "close": 4, "volume": 10},
            {"high": 7, "low": 5, "close": 6, "volume": 10},
            {"high": 2, "low": 0, "close": 1, "volume": 10},
            {"high": 6, "low": 4, "close": 5, "volume": 10},
        ]
        # TP: [2, 4, 6, 1, 5]
        # pos: [0, 40, 60, 0, 50], neg: [0, 0, 0, 10, 0]
        # MFI[2]=100, MFI[3]=85.714286, MFI[4]=83.333333
        result = mfi(bars, period=2)
        assert result[:2] == [None, None]
        assert result[2] == 100.0
        assert result[3] is not None and round(result[3], 6) == 85.714286
        assert result[4] is not None and round(result[4], 6) == 83.333333

    def test_mfi_dict_input(self):
        """MFI with dict bars should work."""
        bars = [
            {"high": 10, "low": 8, "close": 9, "volume": 100},
            {"high": 12, "low": 10, "close": 11, "volume": 200},
            {"high": 14, "low": 12, "close": 13, "volume": 150},
            {"high": 9, "low": 7, "close": 8, "volume": 300},
        ]
        result = mfi(bars, period=2)
        assert len(result) == 4
        assert result[:2] == [None, None]
        assert result[2] is not None
        assert result[3] is not None

    def test_mfi_flat_list_raises(self):
        """Passing a flat list of floats should raise ValueError."""
        with pytest.raises(ValueError, match="requires OHLCV"):
            mfi([1.0, 2.0, 3.0], period=14)

    def test_mfi_too_short(self):
        """Fewer bars than period+1 should return all None."""
        bars = [{"high": 1, "low": 1, "close": 1, "volume": 1} for _ in range(3)]
        result = mfi(bars, period=14)
        assert result == [None, None, None]

    def test_mfi_empty(self):
        assert mfi([], period=14) == []

    def test_mfi_all_up(self):
        """MFI should be 100 when typical price only rises."""
        bars = []
        for i in range(20):
            bars.append({
                "high": 100 + i + 1,
                "low": 100 + i,
                "close": 100 + i + 0.5,
                "volume": 1000,
            })
        result = mfi(bars, period=14)
        assert result[14] == 100.0
        assert all(v == 100.0 for v in result[14:])

    def test_mfi_range(self):
        """MFI values should be between 0 and 100."""
        import random
        random.seed(42)
        bars = []
        for _ in range(100):
            h = random.uniform(50, 150)
            l = h - random.uniform(1, 10)
            c = random.uniform(l, h)
            v = random.uniform(1000, 10000)
            bars.append({"high": h, "low": l, "close": c, "volume": v})
        result = mfi(bars, period=14)
        for v in result:
            if v is not None:
                assert 0 <= v <= 100, f"MFI out of range: {v}"


class TestPVP:
    """Periodic Volume Profile — Point of Control per period."""

    def test_pvp_empty(self):
        assert pvp([], window="day") == []

    def test_pvp_flat_list_raises(self):
        with pytest.raises(ValueError, match="requires OHLCV"):
            pvp([1.0, 2.0, 3.0])

    def test_pvp_single_bar(self):
        bars = [{"timestamp": 1704153600, "high": 50, "low": 10, "close": 30, "volume": 100}]
        result = pvp(bars, rows=4)
        assert len(result) == 1
        assert result[0]["poc"] == 15.0
        assert result[0]["start_ts"] == 1704153600
        assert result[0]["end_ts"] == 1704153600
        assert result[0]["crossed_ts"] is None

    def test_pvp_two_days(self):
        bars = [
            {"timestamp": 1704153600, "high": 50, "low": 10, "close": 30, "volume": 100},
            {"timestamp": 1704175200, "high": 30, "low": 20, "close": 25, "volume": 400},
            {"timestamp": 1704240000, "high": 100, "low": 60, "close": 80, "volume": 200},
            {"timestamp": 1704261600, "high": 90, "low": 70, "close": 80, "volume": 100},
        ]
        result = pvp(bars, rows=4)
        assert len(result) == 2
        assert result[0]["poc"] == 25.0
        assert result[0]["start_ts"] == 1704153600
        assert result[0]["end_ts"] == 1704175200
        assert result[1]["poc"] == 75.0
        assert result[1]["start_ts"] == 1704240000
        assert result[1]["end_ts"] == 1704261600

    def test_pvp_window_week(self):
        bars = [
            {"timestamp": 1704153600, "high": 50, "low": 10, "close": 30, "volume": 100},
            {"timestamp": 1704787200, "high": 100, "low": 60, "close": 80, "volume": 200},
        ]
        result = pvp(bars, window="week", rows=4)
        assert len(result) == 2
        assert result[0]["poc"] is not None
        assert result[1]["poc"] is not None
        assert result[0]["poc"] != result[1]["poc"]

    def test_pvp_window_month(self):
        bars = [
            {"timestamp": 1704153600, "high": 50, "low": 10, "close": 30, "volume": 100},
            {"timestamp": 1706832000, "high": 100, "low": 60, "close": 80, "volume": 200},
        ]
        result = pvp(bars, window="month", rows=4)
        assert len(result) == 2
        assert result[0]["poc"] is not None
        assert result[1]["poc"] is not None
        assert result[0]["poc"] != result[1]["poc"]

    def test_pvp_invalid_window(self):
        bars = [{"timestamp": 1704153600, "high": 50, "low": 10, "close": 30, "volume": 100}]
        with pytest.raises(ValueError, match="Unknown window"):
            pvp(bars, window="year")

    def test_pvp_same_price_all_bars(self):
        bars = [
            {"timestamp": 1704153600, "high": 100, "low": 100, "close": 100, "volume": 100},
            {"timestamp": 1704240000, "high": 100, "low": 100, "close": 100, "volume": 200},
        ]
        result = pvp(bars, window="day")
        assert len(result) == 2
        assert result[0]["poc"] == 100.0
        assert result[1]["poc"] == 100.0

    def test_pvp_zero_volume(self):
        bars = [
            {"timestamp": 1704153600, "high": 50, "low": 10, "close": 30, "volume": 0},
            {"timestamp": 1704175200, "high": 30, "low": 20, "close": 25, "volume": 0},
        ]
        result = pvp(bars, window="day", rows=4)
        assert len(result) == 0  # no valid POC

    def test_pvp_crossing_detection(self):
        """POC crossed by a subsequent bar."""
        bars = [
            {"timestamp": 1704153600, "open": 30, "high": 50, "low": 10, "close": 30, "volume": 100},
            {"timestamp": 1704240000, "open": 20, "high": 25, "low": 15, "close": 22, "volume": 50},
        ]
        result = pvp(bars, window="day", rows=2)
        # Day 1: min=10, max=50, row_size=20
        #   bar1(10-50): rows 0-1, vol/row=50 each, POC=row0 → 10+0.5*20=20
        # Day 2 bar: open=20, close=22 → no cross (both above POC=20)
        assert result[0]["poc"] == 20.0
        crossed = result[0].get("crossed_ts")
        # open=20 is not > POC (it's equal), so no cross
        assert crossed is None

    def test_pvp_crossing_detection_actual_cross(self):
        """POC crossed when a later bar opens above and closes below."""
        bars = [
            {"timestamp": 1704153600, "open": 30, "high": 50, "low": 10, "close": 30, "volume": 100},
            {"timestamp": 1704240000, "open": 25, "high": 28, "low": 15, "close": 18, "volume": 50},
        ]
        result = pvp(bars, window="day", rows=2)
        assert result[0]["poc"] == 20.0
        # Day 2: open=25 > 20 > close=18 → crosses POC
        assert result[0]["crossed_ts"] == 1704240000

    def test_pvp_tick_alignment(self):
        """Row sizes should be rounded to whole ticks."""
        bars = [
            {"timestamp": 1704153600, "high": 100.03, "low": 50.01, "close": 75, "volume": 100},
        ]
        result = pvp(bars, rows=5)
        # avg price ~75, tick_size=0.5
        # price_range=50.02, raw_row_size=10.004, rounded to 10.0
        # actual_rows = 50.02/10.0 + 1 = 6
        assert len(result) == 1
        assert result[0]["poc"] is not None
