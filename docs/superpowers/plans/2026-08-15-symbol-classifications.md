# Symbol Classifications (GICS + TradingView) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `pytvtools_core/classifications.py` module (GICS + TradingView per-ticker taxonomies), a `workspace.chartdata.symbol_classifications` UC table builder notebook, and unit tests — mirroring the existing watchlists / registry patterns.

**Architecture:** A pure-Python core module (`classifications.py`) embeds the GICS hierarchy (273 codes) and a static S&P 500 constituents fallback, and fetches live constituents from GitHub like `get_sp500()` fetches Wikipedia. Two accessors (`get_gics_classifications`, `get_tv_classifications`) return plain dict rows; `classification_rows()` unions them with a `taxonomy` tag for the notebook. The notebook (`cache_classifications.py`) writes a single Delta table via `REPLACE TABLE`, mirroring `cache_registry.py`.

**Tech Stack:** Python ≥3.11, pandas (optional, already a `get_sp500()` dependency), `screen()` from `pytvtools_core.watchlists`, Databricks Spark notebook.

## Global Constraints

- No new runtime dependencies beyond what `watchlists.py` already uses (stdlib `urllib`, optional `pandas`).
- `classifications.py` lives in `src/pytvtools_core/` (carried to core repo by whole-dir copy in `sync_core.py` — no per-file sync change needed).
- GICS symbols normalize to dash form (`.` → `-`) like `get_sp500()`; exchange prefix resolution tolerantly matches `.`/`-` variants returned by the TV scanner.
- GICS sub-industry lookup uses a **level-4-only name index** — never a full-name index (names collide across tiers, e.g. "Building Products" is sub-industry `20102010` AND industry `201020`).
- Table write is full `REPLACE TABLE` (idempotent). No scheduled job — manual-first.
- Every task ends with a commit.

---

### Task 1: GICS hierarchy constant + static constituents snapshot

**Files:**
- Create: `src/pytvtools_core/classifications.py`
- Test: `tests/test_classifications.py`

**Interfaces:**
- Produces: `_GICS_HIERARCHY: dict[str, dict[str, str]]` — `{code: {"name": str, "parent_code": str, "level_num": str}}` for all 273 codes; `_GICS_CONSTITUENTS_STATIC: list[dict[str, str]]` — `{"symbol", "security", "sector", "sub_industry"}` rows (dash-form symbols, e.g. `BRK-B`).

- [ ] **Step 1: Write the failing test**

```python
from pytvtools_core.classifications import _GICS_HIERARCHY, _GICS_CONSTITUENTS_STATIC


def test_hierarchy_counts():
    assert len(_GICS_HIERARCHY) == 273
    levels = {}
    for r in _GICS_HIERARCHY.values():
        levels[r["level_num"]] = levels.get(r["level_num"], 0) + 1
    assert levels == {"1": 11, "2": 25, "3": 74, "4": 163}


def test_hierarchy_parent_links_resolve():
    # every non-sector code's parent must exist in the hierarchy
    for code, r in _GICS_HIERARCHY.items():
        if r["level_num"] == "1":
            continue
        assert r["parent_code"] in _GICS_HIERARCHY, (code, r["parent_code"])


def test_hierarchy_name_collision_building_products():
    # "Building Products" exists at BOTH industry (201020) and sub-industry
    # (20102010) level — name lookups must never use a full-name index.
    codes = [c for c, r in _GICS_HIERARCHY.items() if r["name"] == "Building Products"]
    assert "201020" in codes
    assert "20102010" in codes


def test_static_snapshot_shape():
    assert len(_GICS_CONSTITUENTS_STATIC) >= 490
    row = _GICS_CONSTITUENTS_STATIC[0]
    assert set(row) == {"symbol", "security", "sector", "sub_industry"}
    assert all("." not in r["symbol"] for r in _GICS_CONSTITUENTS_STATIC)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_classifications.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pytvtools_core.classifications'`

- [ ] **Step 3: Build the hierarchy + snapshot constants**

Download the two source files to `/tmp/opencode` (already cached there from this session; refetch if missing):

```bash
curl -s "https://raw.githubusercontent.com/skysaint/gics-data/main/en/gics.csv" -o /tmp/opencode/gics_hierarchy.csv
curl -s "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv" -o /tmp/opencode/sp500_constituents.csv
```

Generate the embedded constants with a helper script (write to `/tmp/opencode/gen_classifications_data.py`):

```python
import csv, json

hier_rows = list(csv.DictReader(open("/tmp/opencode/gics_hierarchy.csv")))
const_rows = list(csv.DictReader(open("/tmp/opencode/sp500_constituents.csv")))

hierarchy = {r["code"]: {"name": r["name"], "parent_code": r["parent_code"],
                         "level_num": r["level_num"]} for r in hier_rows}

snapshot = []
for r in const_rows:
    snapshot.append({
        "symbol": r["Symbol"].replace(".", "-"),
        "security": r["Security"],
        "sector": r["GICS Sector"],
        "sub_industry": r["GICS Sub-Industry"],
    })

with open("/tmp/opencode/classifications_payload.json", "w") as f:
    json.dump({"hierarchy": hierarchy, "snapshot": snapshot}, f, indent=2)
print("hierarchy rows:", len(hierarchy), "snapshot rows:", len(snapshot))
```

Run it, then paste the generated JSON into `classifications.py` as the module constants (keep keys sorted by code for determinism):

```python
"""GICS + TradingView per-ticker classifications.

Pure-Python taxonomy data + fetchers, adjacent to ``watchlists.py``.

Taxonomies:
- ``gics`` — sector / industry_group / industry / sub_industry for S&P 500
  members, rolled up through the embedded 2023 GICS hierarchy.
- ``tv`` — TradingView's ICB-style sector / industry for all US stocks,
  via the scanner API ``screen()``.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from pytvtools_core.watchlists import screen

# 273 GICS codes, 2023 edition: {code: {name, parent_code, level_num}}
_GICS_HIERARCHY: dict[str, dict[str, str]] = {
    # ...generated content...
}

# ~503-row static S&P 500 constituents snapshot (dash-form symbols), used
# only when the live GitHub fetch fails. Mirrors _SP500_TICKERS precedent.
_GICS_CONSTITUENTS_STATIC: list[dict[str, str]] = [
    # ...generated content...
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_classifications.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add src/pytvtools_core/classifications.py tests/test_classifications.py
git commit -m "feat(classifications): embed GICS hierarchy + static S&P 500 snapshot"
```

---

### Task 2: `get_gics_classifications()` — live fetch + roll-up

**Files:**
- Modify: `src/pytvtools_core/classifications.py`
- Test: `tests/test_classifications.py`

**Interfaces:**
- Consumes: `_GICS_HIERARCHY`, `_GICS_CONSTITUENTS_STATIC` (Task 1); `screen()` from `pytvtools_core.watchlists`.
- Produces: `get_gics_classifications(*, force_refetch=False) -> list[dict[str, str]]` — `[{symbol, security, sector, industry_group, industry, sub_industry}]`. `symbol` is exchange-prefixed when the symbol is found in a caller-supplied scan map, else bare dash-form. `_gics_cache: list[dict[str, str]] | None` module-level cache.

- [ ] **Step 1: Write the failing tests**

```python
import pytest

from pytvtools_core.classifications import (
    _fetch_constituents,
    _GICS_CONSTITUENTS_STATIC,
    _gics_cache,
    get_gics_classifications,
)


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """Never hit the network: constituents come from the static snapshot.

    ``get_gics_classifications()`` fetches ``constituents.csv`` on first call,
    so every test replaces the module-level ``_fetch_constituents`` with the
    static snapshot.  (The fallback test below calls the *imported* real
    function directly — unaffected by this module-attribute patch.)
    """
    monkeypatch.setattr(
        "pytvtools_core.classifications._fetch_constituents",
        lambda: [dict(r) for r in _GICS_CONSTITUENTS_STATIC],
    )


def _reset_cache():
    global _gics_cache
    _gics_cache = None


def test_rollup_apple():
    _reset_cache()
    rows = get_gics_classifications(symbol_map={"AAPL": "NASDAQ:AAPL"})
    aapl = [r for r in rows if r["symbol"] == "NASDAQ:AAPL"]
    assert len(aapl) == 1
    r = aapl[0]
    assert r["sector"] == "Information Technology"
    assert r["industry_group"] == "Technology Hardware & Equipment"
    assert r["industry"] == "Technology Hardware, Storage & Peripherals"
    assert r["sub_industry"] == "Technology Hardware, Storage & Peripherals"
    assert r["security"] == "Apple Inc."


def test_rollup_berkshire_dash_and_prefix():
    _reset_cache()
    rows = get_gics_classifications(symbol_map={"BRK-B": "NYSE:BRK.B"})
    brk = [r for r in rows if r["symbol"] == "NYSE:BRK.B"]
    assert len(brk) == 1
    assert brk[0]["sector"] == "Financials"
    assert brk[0]["sub_industry"] == "Multi-Sector Holdings"


def test_unmatched_symbol_stays_bare_dash():
    _reset_cache()
    rows = get_gics_classifications(symbol_map={})
    # pick a symbol known NOT to be prefixed by the empty map
    r = next(x for x in rows if x["symbol"].endswith("-B"))
    assert r["symbol"] == "BRK-B"


def test_fetch_failure_falls_back_to_static(monkeypatch):
    import pandas as pd

    def _boom(*args, **kwargs):
        raise Exception("network down")

    monkeypatch.setattr(pd, "read_csv", _boom)
    rows = _fetch_constituents()
    assert rows == [dict(r) for r in _GICS_CONSTITUENTS_STATIC]


def test_all_static_symbols_roll_up_cleanly():
    _reset_cache()
    rows = get_gics_classifications(symbol_map={})
    assert len(rows) == len(_GICS_CONSTITUENTS_STATIC)
    for r in rows:
        assert r["industry_group"], r
        assert r["industry"], r
        assert r["sector"], r
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_classifications.py -v`
Expected: FAIL with `TypeError: get_gics_classifications() got an unexpected keyword argument 'symbol_map'` (function doesn't exist yet)

- [ ] **Step 3: Implement `get_gics_classifications()`**

```python
_GICS_CONSTITUENTS_URL = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/"
    "main/data/constituents.csv"
)

_gics_cache: list[dict[str, str]] | None = None


def _fetch_constituents() -> list[dict[str, str]]:
    """Fetch live constituents.csv; on any failure return the static snapshot."""
    try:
        import pandas as pd

        df = pd.read_csv(_GICS_CONSTITUENTS_URL)
        rows = []
        for _, row in df.iterrows():
            rows.append({
                "symbol": str(row["Symbol"]).replace(".", "-"),
                "security": str(row["Security"]),
                "sector": str(row["GICS Sector"]),
                "sub_industry": str(row["GICS Sub-Industry"]),
            })
        return rows
    except Exception as exc:  # noqa: BLE001 — mirror get_sp500's blanket fallback
        import logging

        logging.getLogger(__name__).warning(
            "GICS constituents fetch failed (%s); using static snapshot",
            exc,
        )
        return list(_GICS_CONSTITUENTS_STATIC)


def _sub_industry_code_index() -> dict[str, str]:
    """name -> code for LEVEL-4 rows only (names collide across tiers)."""
    idx = {}
    for code, r in _GICS_HIERARCHY.items():
        if r["level_num"] == "4":
            idx.setdefault(r["name"], code)
    return idx


def _rollup(sub_code: str) -> dict[str, str]:
    """Walk parent chain: sub-industry -> industry -> group -> sector."""
    sub = _GICS_HIERARCHY[sub_code]
    ind = _GICS_HIERARCHY[sub["parent_code"]]
    grp = _GICS_HIERARCHY[ind["parent_code"]]
    sec = _GICS_HIERARCHY[grp["parent_code"]]
    return {
        "industry_group": grp["name"],
        "industry": ind["name"],
        "sector": sec["name"],
    }


def _resolve_symbol(
    bare: str, prefix_map: dict[str, str]
) -> str:
    """Prefer an exchange-prefixed match (tolerant of . vs -); else bare."""
    if bare in prefix_map:
        return prefix_map[bare]
    for key, val in prefix_map.items():
        if key.replace("-", ".") == bare.replace("-", "."):
            return val
    return bare


def get_gics_classifications(
    *,
    force_refetch: bool = False,
    symbol_map: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    """S&P 500 member GICS classification with four-tier roll-up.

    Parameters
    ----------
    force_refetch : bool
        Bypass the in-memory cache and refetch constituents.csv.
    symbol_map : dict[str, str] | None
        Mapping ``bare_symbol -> exchange_prefixed_symbol`` (e.g.
        ``{"AAPL": "NASDAQ:AAPL", "BRK-B": "NYSE:BRK.B"}``), used to emit
        ``symbol`` in the same form ``ohlcv`` stores.  Unmatched symbols keep
        bare dash-form.
    """
    global _gics_cache
    if _gics_cache is not None and not force_refetch:
        rows = _gics_cache
    else:
        constituents = _fetch_constituents()
        idx = _sub_industry_code_index()
        rows = []
        for c in constituents:
            sub_code = idx.get(c["sub_industry"])
            if sub_code is None:
                raise ValueError(
                    f"Unknown GICS sub-industry: {c['sub_industry']!r} "
                    f"({c['symbol']})"
                )
            rows.append({
                "symbol": c["symbol"],
                "security": c["security"],
                "sub_industry": c["sub_industry"],
                **_rollup(sub_code),
            })
        _gics_cache = rows

    prefix_map = symbol_map or {}
    out = []
    for r in rows:
        row = dict(r)
        row["symbol"] = _resolve_symbol(r["symbol"], prefix_map)
        out.append(row)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_classifications.py -v`
Expected: 5 PASS (the Task 1 tests still pass too)

- [ ] **Step 5: Commit**

```bash
git add src/pytvtools_core/classifications.py tests/test_classifications.py
git commit -m "feat(classifications): get_gics_classifications with four-tier roll-up"
```

---

### Task 3: `get_tv_classifications()` + `classification_rows()`

**Files:**
- Modify: `src/pytvtools_core/classifications.py`
- Test: `tests/test_classifications.py`

**Interfaces:**
- Consumes: `screen()` from `pytvtools_core.watchlists`; `get_gics_classifications()` (Task 2).
- Produces:
  - `get_tv_classifications(*, market="america", exchanges=("NYSE", "NASDAQ", "AMEX")) -> list[dict[str, str]]` — `[{symbol, sector, industry}]`, symbols exchange-prefixed.
  - `classification_rows(*, force_refetch=False) -> list[dict[str, str | None]]` — `[{symbol, taxonomy, sector, industry_group, industry, sub_industry, security, refreshed_at}]`; `taxonomy` is `"gics"` or `"tv"`; GICS-only columns are `None` for TV rows.

- [ ] **Step 1: Write the failing tests**

```python
from unittest import mock

from pytvtools_core.classifications import (
    classification_rows,
    get_tv_classifications,
)

# Appends to tests/test_classifications.py — the Task 2 imports,
# `_reset_cache()` helper, and the autouse `_offline` fixture (which also
# keeps `force_refetch=True` below offline) already exist in the same file.


def test_get_tv_classifications_uses_screen():
    fake_screen = [
        {"symbol": "NYSE:BRK.B", "sector": "Finance", "industry": "Property/Casualty Insurance"},
        {"symbol": "NASDAQ:GOOGL", "sector": "Technology Services", "industry": "Internet Software/Services"},
    ]
    with mock.patch(
        "pytvtools_core.classifications.screen",
        return_value=(fake_screen, len(fake_screen)),
    ) as scr:
        rows = get_tv_classifications(exchanges=("NYSE",))
    scr.assert_called_once()
    assert rows == [
        {"symbol": "NYSE:BRK.B", "sector": "Finance", "industry": "Property/Casualty Insurance"},
        {"symbol": "NASDAQ:GOOGL", "sector": "Technology Services", "industry": "Internet Software/Services"},
    ]


def test_classification_rows_tags_taxonomy():
    _reset_cache()
    tv_rows = [
        {"symbol": "NYSE:A", "sector": "Finance", "industry": "Major Banks"},
    ]
    with mock.patch(
        "pytvtools_core.classifications.screen",
        return_value=(tv_rows, len(tv_rows)),
    ):
        rows = classification_rows(
            exchanges=("NYSE",), force_refetch=True
        )
    by_tax = {}
    for r in rows:
        by_tax.setdefault(r["taxonomy"], []).append(r)
    # GICS rows present (from static snapshot), TV rows tagged tv
    assert len(by_tax["tv"]) == 1
    tv = by_tax["tv"][0]
    assert tv["symbol"] == "NYSE:A"
    assert tv["taxonomy"] == "tv"
    assert tv["industry_group"] is None
    assert tv["sub_industry"] is None
    assert tv["security"] is None
    assert tv["refreshed_at"] is not None
    # every GICS row must have the full roll-up populated
    for r in by_tax["gics"]:
        assert r["taxonomy"] == "gics"
        assert r["industry_group"] and r["industry"] and r["sector"]
        assert r["industry_group"] is not None
    assert len(by_tax["gics"]) == len(_GICS_CONSTITUENTS_STATIC)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_classifications.py -v`
Expected: FAIL with `ImportError: cannot import name 'get_tv_classifications'`

- [ ] **Step 3: Implement both functions**

```python
def _symbol_map_from_tv(tv_rows: list[dict[str, str]]) -> dict[str, str]:
    """bare -> exchange-prefixed map, tolerant of `.`/`-` (BRK-B vs BRK.B)."""
    out: dict[str, str] = {}
    for r in tv_rows:
        sym = r["symbol"]
        bare = sym.split(":", 1)[1] if ":" in sym else sym
        out[bare.replace("-", ".")] = sym
    return out


def get_tv_classifications(
    *,
    market: str = "america",
    exchanges: tuple[str, ...] = ("NYSE", "NASDAQ", "AMEX"),
) -> list[dict[str, str]]:
    """TradingView ICB-style sector/industry for all US stocks."""
    rows: list[dict[str, str]] = []
    for exch in exchanges:
        screen_rows, _ = screen(market=market, exchange=exch, columns=("sector", "industry"))
        for r in screen_rows:
            rows.append({
                "symbol": str(r["symbol"]),
                "sector": r["sector"] if r["sector"] is not None else "",
                "industry": r["industry"] if r["industry"] is not None else "",
            })
    return rows


def classification_rows(
    *,
    force_refetch: bool = False,
    exchanges: tuple[str, ...] = ("NYSE", "NASDAQ", "AMEX"),
) -> list[dict[str, str | None]]:
    """Union GICS + TV classifications, tagged by taxonomy, with refreshed_at.

    Derives the ``bare -> prefixed`` symbol map from the TV sweep itself
    (single ``screen()`` call per exchange — no second market sweep), then
    feeds it to ``get_gics_classifications`` so the GICS table's ``symbol``
    matches the form ``ohlcv`` stores.
    """
    from datetime import datetime, timezone

    tv = get_tv_classifications(exchanges=exchanges)
    symbol_map = _symbol_map_from_tv(tv)
    gics = get_gics_classifications(
        force_refetch=force_refetch, symbol_map=symbol_map
    )

    refreshed_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, str | None]] = []
    for r in gics:
        rows.append({
            "symbol": r["symbol"],
            "taxonomy": "gics",
            "sector": r["sector"],
            "industry_group": r["industry_group"],
            "industry": r["industry"],
            "sub_industry": r["sub_industry"],
            "security": r["security"],
            "refreshed_at": refreshed_at,
        })
    for r in tv:
        rows.append({
            "symbol": r["symbol"],
            "taxonomy": "tv",
            "sector": r["sector"],
            "industry_group": None,
            "industry": r["industry"],
            "sub_industry": None,
            "security": None,
            "refreshed_at": refreshed_at,
        })
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_classifications.py -v`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add src/pytvtools_core/classifications.py tests/test_classifications.py
git commit -m "feat(classifications): tv classifications + tagged row builder"
```

---

### Task 4: UC builder notebook `cache_classifications.py`

**Files:**
- Create: `notebooks/cache_classifications.py`

**Interfaces:**
- Consumes: `classification_rows()` (Task 3); `_CATALOG` / `_SCHEMA` from `pytvtools_core.cache`.
- Produces: `workspace.chartdata.symbol_classifications` Delta table.

- [ ] **Step 1: Write the notebook**

Mirror `notebooks/cache_registry.py` exactly (cell markers, `%pip install`, `sys.path.insert`). Full content:

```python
# Databricks notebook source
# MAGIC %md
# MAGIC # Symbol Classifications Builder
# MAGIC
# MAGIC Builds/refreshes `workspace.chartdata.symbol_classifications` — one row per
# MAGIC (symbol, taxonomy) for the GICS (S&P 500 members, four-tier roll-up) and
# MAGIC TradingView (all US stocks, ICB-style) taxonomies.
# MAGIC
# MAGIC | Parameter | Value | Source |
# MAGIC |-----------|-------|--------|
# MAGIC | `table` | `workspace.chartdata.symbol_classifications` | UC table |

# COMMAND ----------

# MAGIC %pip install -q websockets

# COMMAND ----------

import sys
sys.path.insert(0, "/Workspace/Users/sl.ilya1987@gmail.com/pytvtools-core/src")

from pyspark.sql.types import (
    StructType, StructField, StringType, TimestampType,
)
from datetime import datetime

from pytvtools_core.classifications import classification_rows
from pytvtools_core.cache import _CATALOG, _SCHEMA

OUTPUT_TABLE = f"{_CATALOG}.{_SCHEMA}.symbol_classifications"
print(f"Building {OUTPUT_TABLE}")

# COMMAND ----------

rows = classification_rows()
print(f"Rows: {len(rows)} "
      f"({sum(1 for r in rows if r['taxonomy'] == 'gics')} gics, "
      f"{sum(1 for r in rows if r['taxonomy'] == 'tv')} tv)")

# COMMAND ----------

df = spark.createDataFrame(rows, schema=StructType([
    StructField("symbol", StringType(), False),
    StructField("taxonomy", StringType(), False),
    StructField("sector", StringType(), True),
    StructField("industry_group", StringType(), True),
    StructField("industry", StringType(), True),
    StructField("sub_industry", StringType(), True),
    StructField("security", StringType(), True),
    StructField("refreshed_at", TimestampType(), True),
])).select(
    "symbol", "taxonomy", "sector", "industry_group",
    "industry", "sub_industry", "security", "refreshed_at",
)

df.createOrReplaceTempView("_classifications_v")
spark.sql(f"CREATE OR REPLACE TABLE {OUTPUT_TABLE} USING DELTA AS SELECT * FROM _classifications_v")

# COMMAND ----------

print(f"Done. {OUTPUT_TABLE}: {spark.table(OUTPUT_TABLE).count()} rows.")
spark.sql(
    f"SELECT taxonomy, count(*) AS n, count(sector) AS with_sector "
    f"FROM {OUTPUT_TABLE} GROUP BY taxonomy ORDER BY taxonomy"
).show(truncate=False)
```

- [ ] **Step 2: Lint-check the notebook parses**

Run: `python3 -m py_compile notebooks/cache_classifications.py`
Expected: exit 0 (no output)

- [ ] **Step 3: Commit**

```bash
git add notebooks/cache_classifications.py
git commit -m "feat(notebooks): symbol classifications UC builder"
```

---

### Task 5: Sync core repo + full test suite

**Files:**
- Modify: `scripts/sync_core.py`
- Test: `tests/test_classifications.py`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: core repo carrying `classifications.py`, `cache_classifications.py`, `test_classifications.py`.

- [ ] **Step 1: Add new files to `sync_core.py` lists**

Modify the lists in `scripts/sync_core.py`:

```python
CORE_TESTS = [
    REPO_ROOT / "tests" / "test_indicators.py",
    REPO_ROOT / "tests" / "test_watchlists.py",
    REPO_ROOT / "tests" / "test_tvdata.py",
    REPO_ROOT / "tests" / "test_measures.py",
    REPO_ROOT / "tests" / "test_classifications.py",
]

CORE_NOTEBOOKS = [
    REPO_ROOT / "notebooks" / "cache_refresh.py",
    REPO_ROOT / "notebooks" / "cache_registry.py",
    REPO_ROOT / "notebooks" / "stress_test_tvdata_limits.py",
    REPO_ROOT / "notebooks" / "absorption_ratio.py",
    REPO_ROOT / "notebooks" / "cache_classifications.py",
]
```

(`classifications.py` needs no entry — `src/pytvtools_core/` is copied whole-dir.)

- [ ] **Step 2: Run the full test suite locally**

Run: `python3 -m pytest tests/ -v`
Expected: all pass, including the new `test_classifications.py`

- [ ] **Step 3: Run the sync**

Run: `python3 scripts/sync_core.py ../pytvtools-core-public --commit "feat(classifications): GICS + TV symbol classifications"`
Expected: sync copies files, commits in the core repo.

- [ ] **Step 4: Verify sync carried the files**

Run:
```bash
ls ../pytvtools-core-public/src/pytvtools_core/classifications.py
ls ../pytvtools-core-public/notebooks/cache_classifications.py
ls ../pytvtools-core-public/tests/test_classifications.py
```
Expected: all three exist.

- [ ] **Step 5: Commit**

```bash
git add scripts/sync_core.py
git commit -m "chore(sync): carry classifications module + notebook + tests to core"
```

---

## Self-Review

**Spec coverage:**
- Embedded hierarchy + static snapshot → Task 1.
- `get_gics_classifications` live fetch + roll-up, level-4-only index, dash-form + prefix resolution → Task 2.
- `get_tv_classifications` via `screen()` → Task 3.
- `classification_rows` union + taxonomy tag + `refreshed_at` → Task 3.
- `symbol_classifications` table schema + `REPLACE TABLE` → Task 4.
- Notebook mirrors `cache_registry.py`, manual-first, no job → Task 4.
- `sync_core.py` additions → Task 5.

**Placeholders:** none — all code blocks are concrete.

**Type consistency:** `classification_rows` returns `dict[str, str | None]`; notebook `createDataFrame` uses the 8-column schema matching the row keys (`symbol, taxonomy, sector, industry_group, industry, sub_industry, security, refreshed_at`). `get_gics_classifications` always returns 6-key rows; `classification_rows` expands to the 8-key shape. `_resolve_symbol` output form matches the `_candidates()` prefix-fallback convention used by `cache.py`.
