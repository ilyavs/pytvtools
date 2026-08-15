# Cap-Weighted Index Construction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable cap-weighted index building block — a pure-numpy `cap_weighted_index()` core function, a `get_market_caps()` scanner helper, and a date-stamped `workspace.chartdata.market_caps` UC table refreshed on demand — for the upcoming absorption-ratio reproduction (GICS-industry portfolios from S&P 500).

**Architecture:** `cap_weighted_index(closes, caps, base)` in `measures.py` builds an index level series with per-date member availability (weights renormalized among members trading both days; new listings ramp in, never truncate). `get_market_caps(symbols)` in `watchlists.py` POSTs a scanner **ticker-list** query for the `market_cap_basic` column. `cache_market_caps.py` (mirrors `cache_classifications.py`) writes one dated snapshot per run to a `market_caps` UC table.

**Tech Stack:** Python ≥3.11, numpy (2.x), stdlib `urllib` (same as `screen()`), Databricks Spark notebook, pytest.

## Global Constraints

- `measures.py` is **numpy-only** — no pandas, no network inside `cap_weighted_index`.
- `watchlists.py` uses only stdlib `urllib` + optional `pandas` (same as `screen()`); `get_market_caps` uses `urllib` only.
- Scanner URL: `https://scanner.tradingview.com/{market}/scan`; request needs the same UA/Referer headers as `screen()`.
- `get_market_caps` POSTs `{"symbols": {"tickers": [...]}, "columns": ["market_cap_basic"], "range": [0, len]}` — ticker-list style, **not** `screen()`'s query style.
- Local test command: `python3 -m pytest tests/test_measures.py tests/test_watchlists.py -q` (host has numpy 2.5.2; container available via `docker exec -w /app docker-pytvtools-1` if needed).
- Notebook follows `cache_classifications.py` conventions: `# Databricks notebook source` + `# MAGIC %md` header, `%pip install -q websockets`, `sys.path.insert(0, "/Workspace/Users/sl.ilya1987@gmail.com/pytvtools-core/src")`, `_CATALOG`/`_SCHEMA` from `pytvtools_core.cache`.
- `market_caps` table is **append-per-snapshot**; same-day re-run deletes today's rows first (idempotent). No scheduled job — manual-first.
- Core repo push workflow: `python3 scripts/sync_core.py ../pytvtools-core-public --commit "MSG"` then `git -C ../pytvtools-core-public push`.
- Every task ends with a commit.

---

### Task 1: `cap_weighted_index()` core function

**Files:**
- Modify: `src/pytvtools_core/measures.py` (append)
- Test: `tests/test_measures.py` (append)

**Interfaces:**
- Consumes: nothing new (numpy imported inside the function, matching `absorption_ratio`).
- Produces: `cap_weighted_index(closes: Any, caps: Any, base: float = 100.0) -> Any` — returns `np.ndarray` shape `(T,)` of index levels; rows before the first date with any member data are `NaN`. Later tasks' notebook reads caps from the UC table and passes them here.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_measures.py`:

```python
from pytvtools_core.measures import absorption_ratio, rolling_absorption_ratio, cap_weighted_index


def test_cap_index_single_member_tracks_price():
    # One active member, one zero-cap member: index = member price scaled to base.
    closes = np.array([
        [10.0, np.nan],
        [11.0, np.nan],
        [12.1, np.nan],
    ])
    levels = cap_weighted_index(closes, caps=np.array([100.0, 0.0]), base=100.0)
    assert levels[0] == pytest.approx(100.0)
    assert levels[1] == pytest.approx(100.0 * 11.0 / 10.0)    # 110.0
    assert levels[2] == pytest.approx(100.0 * 12.1 / 10.0)    # 121.0


def test_cap_index_renormalizes_with_late_joiner():
    # Member A trades all 3 days; member B joins on day 2 (no t-1 close -> ramps
    # in from day 3). Weights renormalize to 0.5/0.5 once B is eligible.
    closes = np.array([
        [100.0, np.nan],
        [110.0, 80.0],
        [121.0, 100.0],
    ])
    caps = np.array([1.0, 1.0])  # equal caps -> renormalized to 0.5/0.5
    levels = cap_weighted_index(closes, caps, base=100.0)
    assert levels[0] == pytest.approx(100.0)
    assert levels[1] == pytest.approx(110.0)  # only A eligible: +10%
    r2 = 0.5 * (121.0 / 110.0 - 1) + 0.5 * (100.0 / 80.0 - 1)  # 0.5*0.1 + 0.5*0.25
    assert levels[2] == pytest.approx(110.0 * (1 + r2))        # 110 * 1.175


def test_cap_index_hand_computed_unequal_caps():
    # A weight 3/4, B weight 1/4 once both eligible.
    closes = np.array([
        [100.0, np.nan],
        [110.0, 200.0],
        [121.0, 220.0],
    ])
    caps = np.array([3.0, 1.0])
    levels = cap_weighted_index(closes, caps, base=1000.0)
    assert levels[0] == pytest.approx(1000.0)
    assert levels[1] == pytest.approx(1100.0)  # A only: +10%
    r2 = 0.75 * (121.0 / 110.0 - 1) + 0.25 * (220.0 / 200.0 - 1)  # 0.75*0.1 + 0.25*0.1
    assert levels[2] == pytest.approx(1100.0 * (1 + r2))          # 1100 * 1.1


def test_cap_index_leading_all_nan_is_nan():
    closes = np.array([
        [np.nan, np.nan],
        [10.0, np.nan],
        [11.0, np.nan],
    ])
    levels = cap_weighted_index(closes, caps=np.array([1.0, 2.0]))
    assert np.isnan(levels[0])
    assert levels[1] == pytest.approx(100.0)
    assert levels[2] == pytest.approx(110.0)


def test_cap_index_zero_cap_does_not_divide_by_zero():
    closes = np.array([
        [10.0, 10.0],
        [11.0, 10.0],
    ])
    caps = np.array([0.0, 1.0])
    levels = cap_weighted_index(closes, caps)
    assert levels[1] == pytest.approx(100.0)  # only the positive-cap member counts


def test_cap_index_no_data_raises():
    closes = np.full((5, 2), np.nan)
    try:
        cap_weighted_index(closes, caps=np.array([1.0, 2.0]))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError when no member has data")


def test_cap_index_caps_length_mismatch_raises():
    closes = np.ones((5, 2))
    try:
        cap_weighted_index(closes, caps=np.array([1.0, 2.0, 3.0]))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError on caps/closes width mismatch")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_measures.py -q`
Expected: FAIL with `ImportError: cannot import name 'cap_weighted_index'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/pytvtools_core/measures.py`:

```python
def cap_weighted_index(
    closes: Any,
    caps: Any,
    base: float = 100.0,
) -> Any:
    """Cap-weighted index level series from member closes + static caps.

    Weights renormalize every date to the members that actually contribute a
    return (data on both that date and the previous one) — a member's first
    trading day has no prior close, so it ramps in from the next day. Members
    with non-positive caps never participate. The index therefore spans the
    oldest available member and is never truncated by a younger listing.

    Parameters
    ----------
    closes : np.ndarray, shape (T, N)
        Close prices, rows = dates (oldest first), cols = members. ``NaN``
        marks a member not trading that date.
    caps : np.ndarray, shape (N,)
        Market caps as-of a snapshot date, held static across time.
    base : float
        Index level at the first date any member trades. Default 100.0.

    Returns
    -------
    np.ndarray, shape (T,)
        Index levels; rows before the first trading date are ``NaN``.
    """
    import numpy as np

    arr = np.asarray(closes, dtype=float)
    w = np.asarray(caps, dtype=float)
    if arr.ndim != 2:
        raise ValueError("closes must be 2-D (T, N)")
    if w.ndim != 1 or w.shape[0] != arr.shape[1]:
        raise ValueError(
            f"caps must be 1-D with length {arr.shape[1]} (got {w.shape})"
        )
    if base <= 0:
        raise ValueError("base must be positive")

    T = arr.shape[0]
    levels = np.full(T, np.nan)
    has_any = ~np.isnan(arr).all(axis=1)
    if not has_any.any():
        raise ValueError("closes has no row with any member data — index undefined")
    start = int(np.argmax(has_any))
    levels[start] = base

    eligible = np.isfinite(arr) & (w > 0)[None, :]  # (T, N) bool
    for t in range(start + 1, T):
        prev_ok = eligible[t - 1]
        now_ok = eligible[t]
        idx = np.flatnonzero(prev_ok & now_ok)
        if idx.size == 0:
            levels[t] = levels[t - 1]  # no member trades both days — carry forward
            continue
        cw = w[idx]
        rets = arr[t, idx] / arr[t - 1, idx] - 1.0
        r = float(np.dot(cw, rets) / cw.sum())
        levels[t] = levels[t - 1] * (1.0 + r)
    return levels
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_measures.py -q`
Expected: PASS (all 13 `test_measures.py` tests, including the 7 new ones).

- [ ] **Step 5: Commit**

```bash
git add src/pytvtools_core/measures.py tests/test_measures.py
git commit -m "feat(measures): cap_weighted_index() with per-date member availability"
```

---

### Task 2: `get_market_caps()` scanner helper

**Files:**
- Modify: `src/pytvtools_core/watchlists.py` (append, near `screen()`)
- Test: `tests/test_watchlists.py` (append)

**Interfaces:**
- Consumes: `_SCANNER_URL` (already defined in `watchlists.py`), stdlib `urllib` (same imports as `screen()`).
- Produces: `get_market_caps(symbols: list[str], market: str = "america", timeout: float = 30.0) -> dict[str, float]` — `{scanner_symbol: market_cap}`. Null caps (delisted / non-tradable) are omitted. Raises `RuntimeError` on HTTP failure. Used by Task 3's notebook.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_watchlists.py`:

```python
class TestGetMarketCaps:
    """get_market_caps() queries the scanner by explicit ticker list."""

    URL = "https://scanner.tradingview.com/america/scan"

    @staticmethod
    def _fake_urlopen(responses):
        seq = iter(responses)

        def _open(req, timeout=None):
            return io.BytesIO(json.dumps(next(seq)).encode())

        return _open

    def test_posts_ticker_list_and_market_cap_basic(self):
        seen = {}

        def _open(req, timeout=None):
            seen["url"] = req.full_url
            seen["data"] = json.loads(req.data.decode())
            return io.BytesIO(json.dumps({
                "totalCount": 2,
                "data": [
                    {"s": "NASDAQ:AAPL", "d": [4460000000000]},
                    {"s": "NYSE:BRK.B", "d": [971000000000]},
                ],
            }).encode())

        with mock.patch("urllib.request.urlopen", side_effect=_open):
            caps = get_market_caps(["AAPL", "BRK.B"])
        assert seen["url"] == TestGetMarketCaps.URL
        assert seen["data"]["symbols"] == {"tickers": ["AAPL", "BRK.B"]}
        assert seen["data"]["columns"] == ["market_cap_basic"]
        assert seen["data"]["range"] == [0, 2]
        assert caps == {
            "NASDAQ:AAPL": 4460000000000.0,
            "NYSE:BRK.B": 971000000000.0,
        }

    def test_drops_null_caps(self):
        resp = {
            "totalCount": 3,
            "data": [
                {"s": "NASDAQ:AAPL", "d": [4460000000000]},
                {"s": "NYSE:X", "d": [None]},
                {"s": "NASDAQ:Y", "d": [None]},
            ],
        }
        with mock.patch("urllib.request.urlopen",
                        side_effect=self._fake_urlopen([resp])):
            caps = get_market_caps(["AAPL", "X", "Y"])
        assert caps == {"NASDAQ:AAPL": 4460000000000.0}

    def test_raises_on_http_error(self):
        def _open(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 500, "boom", {}, None)

        with mock.patch("urllib.request.urlopen", side_effect=_open):
            try:
                get_market_caps(["AAPL"])
            except RuntimeError as exc:
                assert "500" in str(exc)
            else:
                raise AssertionError("expected RuntimeError on HTTP error")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_watchlists.py -q`
Expected: FAIL with `ImportError: cannot import name 'get_market_caps'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/pytvtools_core/watchlists.py` (imports `urllib.error`/`urllib.request` already exist at the top of the file):

```python
def get_market_caps(
    symbols: list[str],
    market: str = "america",
    timeout: float = 30.0,
) -> dict[str, float]:
    """Market caps for an explicit ticker list via the scanner.

    POSTs a ticker-list scan (``symbols.tickers``) requesting only the
    ``market_cap_basic`` column. Returns ``{symbol: cap}`` keyed by the
    scanner's returned symbol (exchange-prefixed, dot-form). Members whose
    cap is null (delisted / non-tradable) are omitted.

    Parameters
    ----------
    symbols : list[str]
        Explicit ticker list, e.g. ``["AAPL", "BRK.B"]``. Pass dot-form
        (``BRK.B``), not dash-form (``BRK-B``).
    market : str
        Scanner market, e.g. ``"america"``.
    timeout : float
        Seconds to wait for the server response.
    """
    caps: dict[str, float] = {}
    chunk_size = 500  # keep each POST modest; the scanner accepts large lists
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i : i + chunk_size]
        payload: dict[str, object] = {
            "symbols": {"tickers": list(chunk)},
            "columns": ["market_cap_basic"],
            "range": [0, len(chunk)],
        }
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            _SCANNER_URL.format(market=market),
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 "
                "Safari/537.36",
                "Referer": "https://www.tradingview.com/screener/",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as err:
            reason = f": {err.reason}" if err.reason else ""
            raise RuntimeError(
                f"get_market_caps({len(symbols)} symbols) failed: HTTP {err.code}{reason}"
            ) from err
        except urllib.error.URLError as err:
            raise RuntimeError(
                f"get_market_caps({len(symbols)} symbols) failed: {err.reason}"
            ) from err

        for item in data.get("data", []):
            values = item.get("d") or []
            cap = values[0] if values else None
            if cap is not None:
                caps[str(item["s"])] = float(cap)
    return caps
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_watchlists.py -q`
Expected: PASS (all prior tests + the 3 new ones).

- [ ] **Step 5: Commit**

```bash
git add src/pytvtools_core/watchlists.py tests/test_watchlists.py
git commit -m "feat(watchlists): get_market_caps() ticker-list scanner helper"
```

---

### Task 3: UC builder notebook `notebooks/cache_market_caps.py`

**Files:**
- Create: `notebooks/cache_market_caps.py`

**Interfaces:**
- Consumes: `get_sp500()` + `get_market_caps()` from `pytvtools_core.watchlists`; `_CATALOG`/`_SCHEMA` from `pytvtools_core.cache`.
- Produces: `workspace.chartdata.market_caps` Delta table `{symbol STRING, market_cap DOUBLE, snapshot_date DATE}` with one dated snapshot appended per run.

- [ ] **Step 1: Write the notebook**

Create `notebooks/cache_market_caps.py` (mirrors `notebooks/cache_classifications.py`):

```python
# Databricks notebook source
# MAGIC %md
# MAGIC # Market Caps Builder
# MAGIC
# MAGIC Refreshes `workspace.chartdata.market_caps` — one row per (symbol,
# MAGIC snapshot_date) holding the current market cap (`market_cap_basic`) of
# MAGIC every S&P 500 member, fetched from the TradingView scanner. Each run
# MAGIC appends a new dated snapshot; re-running on the same day replaces that
# MAGIC day's rows (idempotent). Consumers pick the latest snapshot:
# MAGIC `WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM ...)`.
# MAGIC
# MAGIC | Parameter | Value | Source |
# MAGIC |-----------|-------|--------|
# MAGIC | `table` | `workspace.chartdata.market_caps` | UC table |

# COMMAND ----------

# MAGIC %pip install -q websockets

# COMMAND ----------

import sys
from datetime import datetime, timezone

sys.path.insert(0, "/Workspace/Users/sl.ilya1987@gmail.com/pytvtools-core/src")

from pyspark.sql.types import StructType, StructField, StringType, DoubleType, DateType

from pytvtools_core.watchlists import get_sp500, get_market_caps
from pytvtools_core.cache import _CATALOG, _SCHEMA

OUTPUT_TABLE = f"{_CATALOG}.{_SCHEMA}.market_caps"
print(f"Refreshing {OUTPUT_TABLE}")

# COMMAND ----------

members = list(get_sp500().symbols)
# The scanner expects dot-form tickers (BRK.B) — convert get_sp500()'s dash form.
tickers = [s.replace("-", ".") for s in members]
print(f"S&P 500 members: {len(tickers)}")

caps = get_market_caps(tickers)
print(f"Caps resolved: {len(caps)} / {len(tickers)}")

# COMMAND ----------

snapshot_date = datetime.now(timezone.utc).date()
rows = [
    {"symbol": sym, "market_cap": float(cap), "snapshot_date": snapshot_date}
    for sym, cap in caps.items()
]

df = spark.createDataFrame(rows, schema=StructType([
    StructField("symbol", StringType(), False),
    StructField("market_cap", DoubleType(), False),
    StructField("snapshot_date", DateType(), False),
]))

# Same-day re-run is idempotent: drop today's snapshot, then append.
# Guard the DELETE — the table may not exist on the first run.
from pyspark.sql.utils import AnalysisException
try:
    spark.sql(f"DELETE FROM {OUTPUT_TABLE} WHERE snapshot_date = DATE '{snapshot_date}'")
except AnalysisException:
    pass

df.write.mode("append").saveAsTable(OUTPUT_TABLE)
print(f"Wrote {len(rows)} rows for {snapshot_date}")

# COMMAND ----------

spark.sql(
    f"SELECT snapshot_date, count(*) AS n, round(sum(market_cap)/1e12, 2) AS total_trillion "
    f"FROM {OUTPUT_TABLE} GROUP BY snapshot_date ORDER BY snapshot_date DESC LIMIT 5"
).show(truncate=False)
```

- [ ] **Step 2: Lint-check the notebook parses**

Run: `python3 -m py_compile notebooks/cache_market_caps.py`
Expected: exit 0 (no output). (Notebook is Databricks-only; `py_compile` checks syntax only — top-level `spark`/`%pip` are fine because `# MAGIC` lines are comments.)

- [ ] **Step 3: Commit**

```bash
git add notebooks/cache_market_caps.py
git commit -m "feat(notebooks): date-stamped market caps UC builder"
```

---

### Task 4: Sync core repo + full test suite

**Files:**
- Modify: `scripts/sync_core.py`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: core repo carrying `measures.py`, `watchlists.py`, `cache_market_caps.py`, and the extended test files.

- [ ] **Step 1: Add the notebook to `sync_core.py` lists**

In `scripts/sync_core.py`, add to `CORE_NOTEBOOKS` (alphabetical position, after `cache_classifications.py`):

```python
    REPO_ROOT / "notebooks" / "cache_market_caps.py",
```

(`measures.py`/`watchlists.py` are under `src/pytvtools_core/` — carried whole-dir, no entry needed. `test_measures.py`/`test_watchlists.py` are already in `CORE_TESTS`.)

- [ ] **Step 2: Run the full local test suite**

Run: `python3 -m pytest tests/ -m "not integration" -q`
Expected: all pass (measures + watchlists + classifications + the rest); no regressions from the two modified modules.

- [ ] **Step 3: Run the sync to the core repo**

Run: `python3 scripts/sync_core.py ../pytvtools-core-public --commit "feat(core): cap-weighted index + market caps"`
Expected: copies `src/`, `test_measures.py`, `test_watchlists.py`, `cache_market_caps.py`; commits in the core repo.

- [ ] **Step 4: Verify sync carried the files**

Run:
```bash
ls ../pytvtools-core-public/notebooks/cache_market_caps.py
grep -c "def cap_weighted_index" ../pytvtools-core-public/src/pytvtools_core/measures.py
grep -c "def get_market_caps" ../pytvtools-core-public/src/pytvtools_core/watchlists.py
```
Expected: file exists; each grep prints `1`.

- [ ] **Step 5: Run the core-repo tests**

Run: `PYTHONPATH=/tmp/opencode/dbsite python3 -m pytest tests/test_measures.py tests/test_watchlists.py -q`
Expected: PASS (numpy available on host; the standalone repo has no other deps beyond stdlib).

- [ ] **Step 6: Commit**

```bash
git add scripts/sync_core.py
git commit -m "chore(sync): carry cap-weighted index + market caps to core"
```

---

## Self-Review

**Spec coverage:**
- `cap_weighted_index()` per-date availability, renormalized weights, ramp-in, no truncation → Task 1.
- Weight-normalization invariant, zero-cap no-div-by-zero, leading-NaN, base scaling → Task 1 tests.
- `get_market_caps()` ticker-list payload + `market_cap_basic` + null-cap drop + RuntimeError → Task 2.
- `market_caps` table schema + append-per-snapshot + same-day idempotent DELETE + latest-snapshot consumer → Task 3.
- Manual-first, no job → Task 3 (no job added).
- `sync_core.py` CORE_NOTEBOOKS addition + full suite + core-repo push → Task 4.
- AR reproduction explicitly out of scope → no task (matches spec).

**Placeholders:** none — all code blocks are concrete and complete.

**Type consistency:**
- `cap_weighted_index(closes: Any, caps: Any, base: float = 100.0) -> Any` is identical in Task 1 tests and implementation.
- `get_market_caps(symbols: list[str], market: str = "america", timeout: float = 30.0) -> dict[str, float]` identical in Task 2 tests and implementation, and the notebook calls it with `get_market_caps(tickers)`.
- Notebook passes dot-form tickers (`s.replace("-", ".")`) matching Task 2's documented input contract.
- Table columns `symbol/market_cap/snapshot_date` match the schema in the spec and the notebook's `StructType`/row keys.
