# Formal OHLCV Contract Design

**Date:** 2026-07-11
**Topic:** Formalizing OHLCV data contract

## 1. Goal
Establish a robust contract for OHLCV data across the `pytvtools` and `pytvtools_core` packages using Python type checking (`TypedDict`).

## 2. Architecture
- **`src/pytvtools_core/types.py`**: Define `OHLCVBar` TypedDict.
- **`pytvtools_core` (Indicators)**: Update indicator signatures to use `list[OHLCVBar | float]`.
- **`pytvtools` (TVData/Cache)**: Update type hints for `get_ohlcv` and `query` methods to return `list[OHLCVBar]`.

## 3. Data Contract (`OHLCVBar`)
```python
from typing import TypedDict

class OHLCVBar(TypedDict):
    timestamp: float
    open: float
    high: float
    low: float
    close: float
    volume: float
```

## 4. Implementation Steps
1. **Add `types.py`**: Introduce the `OHLCVBar` TypedDict.
2. **Refactor Signatures**: Apply the new type to existing functions/methods.
3. **Verification**: Run static type checks to ensure compliance.
