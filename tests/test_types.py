import pytest
from pytvtools_core import OHLCVBar

def test_ohlcv_bar_structure():
    bar: OHLCVBar = {
        "timestamp": 1600000000.0,
        "open": 100.0,
        "high": 105.0,
        "low": 95.0,
        "close": 102.0,
        "volume": 1000.0
    }
    assert bar["timestamp"] == 1600000000.0
    assert bar["open"] == 100.0
    assert bar["high"] == 105.0
    assert bar["low"] == 95.0
    assert bar["close"] == 102.0
    assert bar["volume"] == 1000.0
