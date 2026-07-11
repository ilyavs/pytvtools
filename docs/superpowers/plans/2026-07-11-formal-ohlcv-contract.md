# Formal OHLCV Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Formalize the OHLCV data contract using `TypedDict` to ensure type safety across the `pytvtools` packages.

**Architecture:**
- **`src/pytvtools_core/types.py`**: Define `OHLCVBar` TypedDict.
- **`src/pytvtools_core/indicators.py`**: Update function signatures.
- **`src/pytvtools_core/tvdata.py`**: Update return types.
- **`src/pytvtools_core/cache.py`**: Update return types.

**Tech Stack:** Python 3.x, `typing.TypedDict`.

## Global Constraints
- Every bar MUST adhere to the `OHLCVBar` TypedDict structure.
- Backward compatibility must be maintained (the new `TypedDict` is compatible with existing dicts).

---

### Task 1: Define `OHLCVBar`

**Files:**
- Create: `src/pytvtools_core/types.py`

**Interfaces:**
- Produces: `OHLCVBar` (TypedDict)

- [ ] **Step 1: Create `src/pytvtools_core/types.py`**
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

- [ ] **Step 2: Commit**
```bash
git add src/pytvtools_core/types.py
git commit -m "feat: define OHLCVBar TypedDict"
```

### Task 2: Update `indicators.py`

**Files:**
- Modify: `src/pytvtools_core/indicators.py`

**Interfaces:**
- Consumes: `OHLCVBar` from Task 1.

- [ ] **Step 1: Modify `src/pytvtools_core/indicators.py` to import `OHLCVBar` and update function signatures.**
(User needs to read the file first to know which lines to change.)

### Task 3: Update `tvdata.py`

**Files:**
- Modify: `src/pytvtools_core/tvdata.py`

- [ ] **Step 1: Modify `src/pytvtools_core/tvdata.py` to update `get_ohlcv` return type hint.**

### Task 4: Update `cache.py`

**Files:**
- Modify: `src/pytvtools_core/cache.py`

- [ ] **Step 1: Modify `src/pytvtools_core/cache.py` to update return type hints.**

---
