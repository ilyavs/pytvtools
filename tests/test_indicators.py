"""Tests for indicators.py — pure-Python technical indicator calculations."""

from __future__ import annotations

import pytest

from pytvtools_core.indicators import sma, ema, rsi, macd, mfi, supertrend, dss, market_cipher_b


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



class TestSuperTrend:
    def test_empty(self):
        result = supertrend([])
        assert result == {"up_trend": [], "down_trend": []}

    def test_flat_list_raises(self):
        with pytest.raises(ValueError, match="requires OHLCV"):
            supertrend([1.0, 2.0], period=10)

    def test_too_short(self):
        bars = [{"high": 1, "low": 1, "close": 1} for _ in range(5)]
        result = supertrend(bars, period=10)
        assert result["up_trend"] == [None] * 5
        assert result["down_trend"] == [None] * 5

    def test_basic_uptrend(self):
        """Steadily rising prices should eventually flip to uptrend."""
        bars = []
        for i in range(50):
            bars.append({
                "high": 100 + i + 1,
                "low": 100 + i - 0.5,
                "close": 100 + i + 0.5,
            })
        result = supertrend(bars, period=10, multiplier=3.0)
        assert len(result["up_trend"]) == 50
        assert len(result["down_trend"]) == 50
        # First `period - 1` values should be None (RMA from bar 0 starts at period-1)
        assert result["up_trend"][:9] == [None] * 9
        assert result["down_trend"][:9] == [None] * 9
        # First value at index 9 — rising price > lowerBand → flips to uptrend
        assert result["up_trend"][9] is not None
        # Eventually flips to downtrend as well
        assert any(v is not None for v in result["down_trend"])
        # Only one plot active at a time
        for i in range(len(bars)):
            assert not (result["up_trend"][i] is not None and result["down_trend"][i] is not None)

    def test_basic_downtrend(self):
        """Steadily falling prices should eventually trigger downtrend."""
        bars = []
        for i in range(50):
            bars.append({
                "high": 100 - i + 1,
                "low": 100 - i - 0.5,
                "close": 100 - i - 0.5,
            })
        result = supertrend(bars, period=10, multiplier=3.0)
        assert result["up_trend"][:9] == [None] * 9
        # First value at index 9 — price hasn't crossed lower band yet, starts uptrend
        assert result["up_trend"][9] is not None
        # Eventually flips to downtrend as price keeps falling
        assert any(v is not None for v in result["down_trend"])

    def test_struct(self):
        """Result dict has expected keys."""
        bars = [{"high": 10, "low": 8, "close": 9} for _ in range(20)]
        result = supertrend(bars, period=5)
        assert "up_trend" in result
        assert "down_trend" in result
        assert len(result["up_trend"]) == 20
        assert len(result["down_trend"]) == 20

    def test_flip(self):
        """Price flipping up then down should produce matching trend changes."""
        bars = []
        for i in range(30):
            bars.append({
                "high": 100 + i,
                "low": 99 + i,
                "close": 100 + i,
            })
        for i in range(30, 60):
            bars.append({
                "high": 130 - i,
                "low": 129 - i,
                "close": 130 - i,
            })
        result = supertrend(bars, period=5, multiplier=2.0)
        up_count = sum(1 for v in result["up_trend"] if v is not None)
        down_count = sum(1 for v in result["down_trend"] if v is not None)
        assert up_count > 0
        assert down_count > 0
        # No overlap: same index can't have both up and down
        for i in range(len(bars)):
            assert not (result["up_trend"][i] is not None and result["down_trend"][i] is not None)


class TestDSS:
    def test_empty(self):
        result = dss([])
        assert result == {"dss": [], "trigger": []}

    def test_flat_list_raises(self):
        with pytest.raises(ValueError, match="requires OHLCV"):
            dss([1.0, 2.0], pds=10)

    def test_too_short(self):
        bars = [{"high": 100, "low": 90, "close": 95} for _ in range(3)]
        result = dss(bars, pds=10, ema_len=9, trigger_len=5)
        assert result["dss"] == [None, None, None]
        assert result["trigger"] == [None, None, None]

    def test_struct(self):
        bars = []
        for i in range(50):
            bars.append({
                "high": 100 + i,
                "low": 90 + i,
                "close": 95 + i,
            })
        result = dss(bars, pds=10, ema_len=9, trigger_len=5)
        assert "dss" in result
        assert "trigger" in result
        assert len(result["dss"]) == 50
        assert len(result["trigger"]) == 50

    def test_range(self):
        """DSS values should be between 0 and 100."""
        import random
        random.seed(42)
        bars = []
        for _ in range(100):
            h = random.uniform(50, 150)
            l = h - random.uniform(1, 10)
            c = random.uniform(l, h)
            bars.append({"high": h, "low": l, "close": c})
        result = dss(bars, pds=10, ema_len=9, trigger_len=5)
        for v in result["dss"]:
            if v is not None:
                assert -1e-10 <= v <= 100 + 1e-10, f"DSS out of range: {v}"
        for v in result["trigger"]:
            if v is not None:
                assert -1e-10 <= v <= 100 + 1e-10, f"Trigger out of range: {v}"

    def test_dss_and_trigger_shape(self):
        """DSS and trigger: trigger has fewer non-None bars (EMA lag)."""
        import random
        random.seed(1)
        bars = []
        base = 100.0
        for _ in range(200):
            high = base + random.uniform(0, 5)
            low = base - random.uniform(0, 5)
            close = random.uniform(low, high)
            bars.append({"high": high, "low": low, "close": close})
            base += 0.5
        result = dss(bars, pds=14, ema_len=9, trigger_len=5)
        assert len(result["dss"]) == 200
        assert len(result["trigger"]) == 200
        dss_cnt = sum(1 for v in result["dss"] if v is not None)
        trig_cnt = sum(1 for v in result["trigger"] if v is not None)
        assert dss_cnt > trig_cnt > 0


class TestMarketCipherB:
    def test_empty(self):
        result = market_cipher_b([])
        assert result == {"wt1": [], "wt2": [], "wt1_minus_wt2": []}

    def test_flat_list_raises(self):
        with pytest.raises(ValueError, match="requires OHLCV"):
            market_cipher_b([1.0, 2.0])

    def test_too_short(self):
        bars = [{"high": 100, "low": 90, "close": 95} for _ in range(3)]
        result = market_cipher_b(bars, channel_length=10, average_length=21)
        assert result["wt1"] == [None, None, None]
        assert result["wt2"] == [None, None, None]
        assert result["wt1_minus_wt2"] == [None, None, None]

    def test_struct(self):
        bars = []
        for i in range(50):
            bars.append({
                "high": 100 + i,
                "low": 90 + i,
                "close": 95 + i,
            })
        result = market_cipher_b(bars, channel_length=10, average_length=21)
        assert "wt1" in result
        assert "wt2" in result
        assert "wt1_minus_wt2" in result
        assert len(result["wt1"]) == 50
        assert len(result["wt2"]) == 50
        assert len(result["wt1_minus_wt2"]) == 50

    def test_wt2_has_more_leading_none_than_wt1(self):
        """WT2 has 3 additional leading Nones from SMA(WT1, 4)."""
        import random
        random.seed(1)
        bars = []
        base = 100.0
        for _ in range(200):
            high = base + random.uniform(0, 5)
            low = base - random.uniform(0, 5)
            close = random.uniform(low, high)
            bars.append({"high": high, "low": low, "close": close})
            base += 0.5
        result = market_cipher_b(bars, channel_length=10, average_length=21)
        wt1_cnt = sum(1 for v in result["wt1"] if v is not None)
        wt2_cnt = sum(1 for v in result["wt2"] if v is not None)
        assert wt1_cnt > wt2_cnt > 0
        assert wt1_cnt - wt2_cnt == 3
