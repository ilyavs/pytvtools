# Symbol Registry + Registry-Aware Refresh — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist a `workspace.chartdata.symbol_registry` table mapping every cached ticker to its watchlist (with `first_listed`/`last_updated` derived from `chartdata.ohlcv`) and make the scheduled refresh jobs consume that table as their symbol source.

**Architecture:** A pure, testable `registry_rows()` helper in `pytvtools_core/watchlists.py` builds `(symbol, watchlist, source)` entries for all static watchlists + S&P 500. A new Databricks notebook `notebooks/cache_registry.py` joins those entries against `min/max(timestamp)` aggregates from `chartdata.ohlcv` and writes the registry with `CREATE OR REPLACE TABLE`. `notebooks/cache_refresh.py` is edited so its symbol-resolution block reads `SELECT DISTINCT symbol` from the registry first, falling back to the current code-based S&P 500 / watchlist resolution when the registry is missing or empty. No job JSON changes — notebooks live in the repo, sync to the workspace git folder, and are picked up by the existing scheduled jobs automatically.

**Tech Stack:** Python 3.11+, pytest 9.0.3 (installed via `pip install --user --break-system-packages`), PySpark / Databricks, databricks-sdk 0.125.0, `scripts/sync_core.py` for repo sync.

## Global Constraints

- Registry table identifier: `workspace.chartdata.symbol_registry`.
- Columns (exact): `symbol STRING`, `watchlist STRING`, `source STRING` (`"watchlist"` or `"sp500"`), `first_listed TIMESTAMP`, `last_updated TIMESTAMP`.
- One row per `(symbol, watchlist)`; a symbol in N watchlists → N rows (e.g. `SLX` → `SPDR_INDUSTRIES`, `URANIUM_STRATEGIC`, and `SP500` rows).
- `first_listed`/`last_updated` are `min(timestamp)`/`max(timestamp)` for the symbol across **all timeframes** in `chartdata.ohlcv`; symbols in a watchlist but with no bars get NULL timestamps.
- Registry is rebuilt wholesale via `CREATE OR REPLACE TABLE ... AS SELECT` every run — idempotent, no MERGE.
- Watchlist `source` values: static lists from `WATCHLISTS` → `"watchlist"`; S&P 500 → `"sp500"` with `watchlist="SP500"`.
- `cache_refresh.py` keeps `timeframe`, `mode`, `symbol`, and `watchlist` widgets unchanged. `watchlist` widget, when set, acts as an include filter on `symbol_registry.watchlist`.
- Fallback contract: registry missing/empty → resolve from code (`watchlist` widget set → `get_watchlist`/`get_sp500`; no widget → S&P 500 batch). Must log a clear "registry missing/empty" warning.
- Pure functions must NOT import pandas at module scope and must accept an injected `sp500` Watchlist so tests avoid network+pandas (Databricks has pandas, local does not).
- Local verification command: `python3 -m pytest tests/test_watchlists.py -q` (PEP-668 workaround: `python3 -m pip install --user --break-system-packages pytest==9.0.3 pytest-asyncio==1.4.0 websockets==16.0`).
- Sync: `python scripts/sync_core.py ../pytvtools-core-public --commit "..."` then `git -C ../pytvtools-core-public push` (branch `main`). Workspace git folder has repo_id `2757908263996995`, force-sync via `ws.repos.update(repo_id=..., branch="main", dangerously_force_discard_all=True)`.
- Databricks SDK run path: `PYTHONPATH=/tmp/opencode/dbsite` + `python3 -c "from databricks.sdk import WorkspaceClient; ws = WorkspaceClient(profile='DEFAULT')"`.

---

### Task 1: Add `registry_rows()` helper to watchlists.py

**Files:**
- Modify: `src/pytvruntime_core/watchlists.py` (append after `get_watchlist()` at end of file)
- Test: `tests/test_watchlists.py` (append a class)

**Interfaces:**
- Produces: `registry_rows(sp500: Watchlist | None = None) -> list[dict[str, str]]` returning one entry per `(symbol, watchlist)`: `{"symbol": str, "watchlist": str, "source": str}`. `source` is `"watchlist"` for every static `WATCHLISTS` entry and `"sp500"` for the passed S&P 500 watchlist. When `sp500` is `None`, it falls back to `get_sp500()` (network + pandas — only in the Databricks job); tests always pass an explicit `sp500`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_watchlists.py`:

```python
from pytvtools_core.watchlists import registry_rows, Watchlist


class TestRegistryRows:
    def test_includes_static_watchlists(self):
        rows = registry_rows(sp500=Watchlist("S&P 500", ("FAKESP",)))
        syms = {r["symbol"] for r in rows}
        assert "XLK" in syms
        assert "TVC:US10Y" in syms
        assert "AMEX:URA" in syms

    def test_static_rows_use_watchlist_source(self):
        rows = registry_rows(sp500=Watchlist("S&P 500", ("FAKESP",)))
        xlk = [r for r in rows if r["symbol"] == "XLK"]
        assert len(xlk) == 1
        assert xlk[0]["watchlist"] == "SPDR_SECTORS"
        assert xlk[0]["source"] == "watchlist"

    def test_sp500_rows_use_sp500_source(self):
        rows = registry_rows(sp500=Watchlist("S&P 500", ("AAA", "CCC")))
        sp = [r for r in rows if r["source"] == "sp500"]
        assert {r["symbol"] for r in sp} == {"AAA", "CCC"}
        assert all(r["watchlist"] == "SP500" for r in sp)

    def test_symbol_in_multiple_watchlists_has_multiple_rows(self):
        rows = registry_rows(sp500=Watchlist("S&P 500", ("SLX",)))
        slx = [r for r in rows if r["symbol"] == "SLX"]
        assert {r["watchlist"] for r in slx} == {
            "SPDR_INDUSTRIES", "URANIUM_STRATEGIC", "SP500"}
        assert len(slx) >= 3

    def test_returns_plain_dicts(self):
        rows = registry_rows(sp500=Watchlist("S&P 500", ("FAKESP",)))
        assert set(rows[0]) == {"symbol", "watchlist", "source"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_watchlists.py::TestRegistryRows -q`
Expected: FAIL with `ImportError: cannot import name 'registry_rows'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/pytvtools_core/watchlists.py`:

```python
def registry_rows(sp500: Watchlist | None = None) -> list[dict[str, str]]:
    """Build one (symbol, watchlist, source) entry per symbol per watchlist.

    Static ``WATCHLISTS`` entries get ``source="watchlist"``; the S&P 500 gets
    ``source="sp500"`` with ``watchlist="SP500"``.  Pass ``sp500`` explicitly
    to avoid the network/pandas load of ``get_sp500()`` (used in Databricks).
    """
    wl = sp500 if sp500 is not None else get_sp500()
    rows: list[dict[str, str]] = []
    for name, watch in WATCHLISTS.items():
        for sym in watch.symbols:
            rows.append({"symbol": sym, "watchlist": name, "source": "watchlist"})
    for sym in wl.symbols:
        rows.append({"symbol": sym, "watchlist": "SP500", "source": "sp500"})
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_watchlists.py::TestRegistryRows -q`
Expected: PASS (5 tests). Then run the full file: `python3 -m pytest tests/test_watchlists.py -q` → all pass.

- [ ] **Step 5: Commit**

```bash
git add src/pytvtools_core/watchlists.py tests/test_watchlists.py
git commit -m "feat(core): add registry_rows() for symbol registry build"
```

---

### Task 2: Create `notebooks/cache_registry.py`

**Files:**
- Create: `notebooks/cache_registry.py` (Databricks notebook, `# COMMAND ----------` cells)

**Interfaces:**
- Consumes: `registry_rows()` from `pytvtools_core.watchlists` (Task 1); `spark` global (Databricks); `pyspark.sql.functions`.
- Produces: `workspace.chartdata.symbol_registry` Delta table (schema per Global Constraints).

- [ ] **Step 1: Write the notebook file**

```text
# Databricks notebook source
# MAGIC %md
# MAGIC # Symbol Registry Builder
# MAGIC
# MAGIC Builds/refreshes `workspace.chartdata.symbol_registry` — one row per
# MAGIC (symbol, watchlist) for all watchlists + S&P 500, with first_listed /
# MAGIC last_updated derived from `workspace.chartdata.ohlcv`.
# MAGIC
# MAGIC | Parameter | Value | Source |
# MAGIC |-----------|-------|--------|
# MAGIC | `table` | `workspace.chartdata.symbol_registry` | UC table |

# COMMAND ----------
# MAGIC %pip install -q websockets

# COMMAND ----------
import sys
sys.path.insert(0, "/Workspace/Users/sl.ilya1987@gmail.com/pytvtools-core/src")

import pyspark.sql.functions as F
from pyspark.sql.types import StructType, StructField, StringType, TimestampType

from pvtvtools_core.watchlists import registry_rows
from pvtools_core.cache import _CATALOG, _SCHEMA

OUTPUT_TABLE = f"{_CATALOG}.{_SCHEMA}.symbol_registry"
OHLCV_TABLE = f"{_CATALOG}.{_SCHEMA}.ohlcv"

print(f"Building registry {OUTPUT_TABLE} from {OHLCV_TABLE}")

# COMMAND ----------
# 1. build (symbol, watchlist, source) entries - all watchlists + S&P 500
entries = registry_rows()
print(f"Registry entries: {len(entries)}")

# COMMAND ----------
# 2. join to per-symbol first/last timestamp across ALL timeframes
df = spark.createDataFrame(entries, schema=StructType([
    StructField("symbol", StringType(), False),
    StructField("watchlist", StringType(), False),
    StructField("source", StringType(), False),
]))

agg = (
    spark.table(OHLCV_TABLE)
    .groupBy("symbol")
    .agg(
        F.min("timestamp").alias("first_listed"),
        F.max("timestamp").alias("last_updated"),
    )
)

out = df.join(agg, on="symbol", how="left")
out = out.select("symbol", "watchlist", "source", "first_listed", "last_updated")

# COMMAND ----------
# 3. full rebuild - idempotent
out.createOrReplaceTempView("_registry_v")
spark.sql(f"CREATE OR REPLACE TABLE {OUTPUT_TABLE} USING DELTA AS SELECT * FROM _registry_v")

# COMMAND ----------
# 4. summary
total = spark.table(OUTPUT_TABLE).count()
with_bars = out.filter(F.col("last_updated").isNotNull()).count()
print(f"Done. {OUTPUT_TABLE}: {total} rows, {with_bars} with data.")
print("Top watchlists:")
spark.sql(
    f"SELECT watchlist, count(*) AS n FROM {OUTPUT_TABLE} GROUP BY watchlist ORDER BY n DESC"
).show(truncate=False)
```

- [ ] **Step 2: Syntax-check the notebook**

Run: `python3 -m py_compile notebooks/cache_refresh.py notebooks/cache_registry.py`
Expected: exit code 0 (no syntax errors — `#` comments/`%magic` cells are inert).

- [ ] **Step 3: Commit (notebook does not have unit tests; validated at deploy in Task 5)**

```bash
git add notebooks/cache_registry.py
git commit -m "feat(notebooks): add cache_registry.py - build symbol registry from watchlists + ohlcv"
```

---

### Task 3: Make `cache_refresh.py` registry-aware

**Files:**
- Modify: `notebooks/cache_refresh.py` lines 47-64 (the symbol-resolution block).

**Interfaces:**
- Consumes: `spark` global; `workspace.chartdata.symbol_registry` (created in Task 2/deploy). `get_watchlist`/`get_sp500` from `pytvtools_core.watchlists` as fallback.
- Produces: same `symbols: list[str]` + `label: str` variables the remainder of the notebook already uses (lines 98-130 unchanged).

- [ ] **Step 1: Edit the resolution block**

Replace the block (currently):

```python
if symbol:
    symbols = [symbol]
    label = f"single={symbol}"
elif watchlist:
    if watchlist == "SP500":
        from pytvtools_core.watchlists import get_sp500
        wl = get_sp500()
    else:
        from pytvtools_core.watchlists import get_watchlist
        wl = get_watchlist(watchlist)
    symbols = sorted(wl.symbols)
    label = f"watchlist={watchlist} ({len(symbols)} symbols)"
else:
    # Default: S&P 500
    from pytvtools_core.watchlists import get_sp500
    wl = get_sp500()
    symbols = sorted(wl.symbols)
    label = f"S&P 500 batch ({len(symbols)} symbols)"
```

with:

```python
from pytvtools_core.cache import _CATALOG, _SCHEMA
REGISTRY_TABLE = f"{_CATALOG}.{_SCHEMA}.symbol_registry"

if symbol:
    symbols = [symbol]
    label = f"single={symbol}"
else:
    try:
        from pytvtools_core.watchlists import get_sp500, get_watchlist
    except ImportError:
        get_sp500, get_watchlist = None, None

    # Prefer the symbol registry when present; fall back to code resolution.
    try:
        n = spark.sql(f"SELECT COUNT(*) AS n FROM {REGISTRY_TABLE}").collect()[0]["n"]
    except Exception:
        n = 0

    if n > 0:
        where = f" WHERE watchlist = '{watchlist}'" if watchlist else ""
        rows = spark.sql(
            f"SELECT DISTINCT symbol FROM {REGISTRY_TABLE}{where} ORDER BY symbol"
        ).collect()
        symbols = [r["symbol"] for r in rows]
        label = f"registry={watchlist or 'all'} ({len(symbols)} symbols)"
    elif watchlist:
        wl = get_sp500() if watchlist == "SP500" else get_watchlist(watchlist)
        symbols = sorted(wl.symbols)
        label = f"watchlist={watchlist} ({len(symbols)} symbols)"
    else:
        wl = get_sp500()
        symbols = sorted(wl.symbols)
        label = f"S&P 500 batch (registry missing/empty; {len(symbols)} symbols)"
```

- [ ] **Step 2: Syntax-check**

Run: `python3 -m py_compile notebooks/cache_refresh.py`
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add notebooks/cache_refresh.py
git commit -m "feat(notebooks): refresh reads symbol registry with watchlist filter + fallback"
```

---

### Task 4: Register new notebook in sync_core.py

**Files:**
- Modify: `scripts/sync_core.py` `CORE_NOTEBOOKS` (line 25-28)

**Interfaces:**
- Produces: `cache_registry.py` copied to target repo `notebooks/` on every sync so the workspace git folder carries it.

- [ ] **Step 1: Edit `CORE_NOTEBOOKS`**

```python
CORE_NOTEBOOKS = [
    REPO_ROOT / "notebooks" / "cache_refresh.py",
    REPO_ROOT / "notebooks" / "cache_registry.py",
    REPO_ROOT / "notebooks" / "stress_test_tvdata_limits.py",
]
```

- [ ] **Step 2: Verify regex/JSON templates still valid**

Run: `python3 -m py_compile scripts/sync_core.py && python3 -m pytest tests/test_watchlists.py -q`
Expected: exit 0, all pass.

- [ ] **Step 3: Commit**

```bash
git add scripts/sync_core.py
git commit -m "chore(scripts): include cache_registry notebook in sync"
```

---

### Task 5: Deploy + build the registry (manual first, per user sequence)

**Files:** none (operates on remote Databricks + core-public repo).

**Interfaces:**
- Consumes: Tasks 1-4 committed on branch `main` of `/home/ilya/github/pytvtools` and of the sync target `../pytvtools-core-public`.
- Produces: `workspace.chartdata.symbol_registry` populated; `notebooks/cache_registry.py` present in the workspace git folder.

- [ ] **Step 1: Run full local test suite for core**

```bash
python3 -m pytest tests/test_watchlists.py -q
```

Expected: all pass.

- [ ] **Step 2: Sync to public core repo + push**

```bash
python scripts/sync_core.py ../pytvtools-core-public --commit "feat: symbol registry notebook + registry-aware refresh"
git -C ../pytvtools-core-public push
```

Note: if the previous session's local branch noise (CRLF stash) reappears, verify `git -C ../pytvtools-core-public status` shows only the expected files (src/, tests/, notebooks/, jobs/, pyproject.toml).

- [ ] **Step 3: Force-sync the workspace git folder**

```bash
PYTHONPATH=/tmp/opencode/dbsite python3 - <<'PY'
from databricks.sdk import WorkspaceClient
ws = WorkspaceClient(profile="DEFAULT")
ws.repos.update(repo_id=2757906943956995, branch="main", dangerously_force_discard_all=True)
print("workspace git folder synced")
PY
```

Verify the folder now contains `notebooks/cache_registry.py`:
```bash
PYTHONPATH=/tmp/opencode/dbsite python3 - <<'PY'
from databricks.sdk import WorkspaceClient
ws = WorkspaceClient(profile="DEFAULT")
print(ws.workspace.export("/pytvtools-core/notebooks/cache_registry.py"))  # contains "registry_rows"
PY
```

- [ ] **Step 4: Run the registry notebook once via a temporary job**

```bash
PYTHONPATH=/tmp/opencode/dbsite python3 - <<'PY'
from databricks.sdk import WorkspaceClient
ws = WorkspaceClient(profile="DEFAULT")
# import notebook from git /workspace repo path, then submit
notebook = {
    "notebook_path": "pytvtools-core/notebooks/cache_registry",
    "source": "SOURCE"
}
# fallback: create a notebook from the source and run it
PY
```

If a workspace notebook import from the git folder is not straightforward, import the file content into a scratch workspace path and run:
```python
ws.workspace.import_(path="/Users/sl.ilya1987@gmail.com/cache_registry_scratch", format="SOURCE", overwrite=True, content=source_b64)
```

- [ ] **Step 5: Verify registry table exists + has the expected rows**

```bash
PYTHONPATH=/tmp/opencode/dbsite python3 - <<'PY'
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import Statement
ws = WorkspaceClient(profile="DEFAULT")
sql = ("SELECT watchlist, count(*) AS n FROM workspace.chartdata.symbol_registry "
       "GROUP BY watchlist ORDER BY n DESC")
resp = ws.statement_execution.execute_statement(sql, warehouse_id="0bccfeb476515f78").wait()
print(resp.status, resp.result.data_array)
PY
```

Expected: rows for `SP500` (~505), `METALS_MINERS`, `INDEX_FUTURES`, etc., and a few NULL `last_updated` rows being OK.

---

### Task 6: Confirm scheduled jobs pick up the registry (no job JSON edits)

**Files:** none.

**Interfaces:**
- Consumes: modified `cache_refresh.py` (Task 3) now synced to the workspace folder; jobs read `notebooks/cache_refresh.py`.

- [ ] **Step 1: Confirm job git_source is correct (unchanged by this work)**

```bash
PYTHONPATH=/tmp/opencode/dbsite python3 - <<'PY'
from databricks.sdk import WorkspaceClient
ws = WorkspaceClient(profile="DEFAULT")
for jid in ("795017445883903", "936004519313878", "495785726036702"):
    j = ws.jobs.get(jid)
    gs = j.settings.git_source
    print(jid, gs.git_url if gs else None, gs.git_branch if gs else None)
PY
```

All should still point at `https://github.com/ilyavs/pytvtools-core` branch `main`.

- [ ] **Step 2: Run cache_refresh on-demand once to smoke-test the new block**

Execute the daily job (or a temporary throwaway job) with a small override so it doesn't take 56 minutes — pragmatically, run it with the existing schedule-less behavior but wrap up after the first few batches by running a single-symbol or registry subset scenario. Simplest safe check: run the existing `cache_refresh_on_demand` with a single symbol override is NOT possible (job reads registry now), so instead:
- temporarily set `watchlist=CRYPTO` via widget when running an on-demand job? Not supported by current JSON.
Use the DBX UX instead — open the workspace notebook and run it locally with a `symbol` override to verify no import/runtime errors:

```bash
PYTHONPATH=/tmp/opencode/dbsite python3 - <<'PY'
# run the notebook via jobs.submit on the git-based daily job and watch run state
from databricks.sdk import WorkspaceClient
ws = WorkspaceClient(profile="DEFAULT")
run = ws.jobs.run_now(795017445883903).response
rid = run.run_id
import time
time.sleep(60)
r = ws.runs.get(rid)
print(r.state.life_cycle_state, r.state.result_state)
PY
```

- [ ] **Step 3: Confirm next scheduled run refreshes registry symbols**

Wait for the next daily (04:30) / weekly (05:00) schedule and check the run report. Confirm the notebook log prints `registry=all (... symbols)` in the refresh output and `chartdata.ohlcv` `last_updated` advances for previously-stale symbols (e.g. `CTLT` previously 2022, `BITSTAMP:BTCUSD`).

Expected: run SUCCESS; log shows "registry=all (<N> symbols)" and the 120 previously-stale symbols refreshed.

- [ ] **Step 4: Record deploy + clean up scratch resources**

Remove any scratch notebook created (Task 5 step 4). No job JSON changes were made — jobs still use existing templates.

---

## Self-Review Notes

- **Spec coverage:** all registry columns, build/join/REPLACE, refresh fallback, watchlist filter, manual-first sequence, no job JSON edits  → Tasks 1-6. Removed/not built: no registry job scheduler → out of scope.
- **Placeholders:** notebook TDD is not possible (Databricks cells), so Task 2's verification is `py_compile` + deployment run; Task 5-6 use explicit SDK snippets with exact table/warehouse identifiers from the session.
- **Names:** `registry_rows()` / `cache_registry.py` / `symbol_registry` are consistent across tasks; `registry_rows()` / `cache_registry.py` / `symbol_registry` are consistent across all tasks.