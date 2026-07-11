from typing import TypedDict

class OHLCVBar(TypedDict):
    timestamp: float
    open: float
    high: float
    low: float
    close: float
    volume: float
