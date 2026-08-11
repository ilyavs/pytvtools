# US Stocks into `ohlcv` (1D/1W/1M) via symbol registry — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest ~5701 US-listed stocks (NYSE/NASDAQ/AMEX) into `workspace.chartdata.ohlcv` with full-history 1D/1W/1M bars, driven by the symbol registry (`us_stock_rows()` feeds `cache_registry.py` → `symbol_registry` → scheduled/backfill `cache_refresh` jobs).

**Architecture:** `pytvtools_core/watchlists.py` gains `us_stock_rows()` (unions `screen(exchange=...)` results per exchange → `{symbol, watchlist:"US_STOCKS", source:"screen"}` rows) and `get_us_stocks()` (lazy `Watchlist`, mirrors `get_sp500`). `notebooks/cache_registry.py` appends those rows to the registry rebuild. `notebooks/cache_refresh.py` adds a `concurrency` widget (default `1`) and a `US_STOCKS` fallback case. Job configs (templates in `pytvtools-core-public/jobs/`) get `timeout_seconds` 3600→21600 and the `git_source` regression fixed, then re-applied to live jobs. Backfill runs through the existing on-demand job 3× (1D/1W/1M).

**Tech Stack:** Python 3.11+, pytest 9.0.3, Databricks (PySpark notebooks), databricks-sdk 0.125.0 via `PYTHONPATH=/tmp/opencode/dbsite`, `scripts/sync_core.py` for repo sync, TradingView scanner API (`screen()`).

## Global Constraints

- Registry is rebuilt wholesale (`CREATE OR REPLACE TABLE ... AS SELECT`) — no MERGE. One row per `(symbol, watchlist)`.
- New row shape: `{"symbol": "NYSE:A", "watchlist": "US_STOCKS", "source": "screen"}`, symbols exchange-prefixed as returned by `screen()` (never bare).
- `cache_refresh.py` keeps `timeframe`, `mode`, `symbol`, `watchlist` widgets unchanged; ADDS a `concurrency` widget defaulting to `"1"` (rate-limit safety — do NOT default higher).
- Rate limits trump speed: concurrency stays 1 unless a human changes the widget; jittered sleeps, batch sizes, and retry-with-backoff in `cache.py` remain untouched.
- Local test command: `python3 -m pytest tests/test_watchlists.py -q` (pytest already installed). Pure functions must not hit the network in tests — mock `urllib.request.urlopen`.
- Sync flow unchanged: `python scripts/sync_core.py ../pytvtools-core-public --commit "MSG"` then `git -C ../pytvtools-core-public push`; force-sync workspace git folder `repo_id=2757908263996995` via `PYTHONPATH=/tmp/opencode/dbsite python3` + `ws.repos.update(repo_id=..., branch="main", dangerously_force_discard_all=True)`.
- Live job IDs: daily `795017445883903` (1D), weekly `936004519313878` (1W), monthly `495726785036702` (1M), on-demand `646435410260973`. Live jobs' `git_source` is `ilyavs/pytvtools-core @ main` (verified). Template JSONs in `pytvtools-core-public/jobs/` currently say `ilyavs/pytvtools-core-public @ master` — fix them. (Monthly ID corrected from an earlier plan draft `495785726036702` — the actual live job is `495726785036702`, confirmed via `ws.jobs.get`.)
- Databricks SQL runpath (SDK): `execute_statement(..., warehouse_id="0bccfeb476515f78")` returns the `StatementResponse` directly — check `resp.status.state == StatementState.SUCCEEDED`, read `resp.result.data_array`.
- In the SDK, `ws.jobs.list()` returns job IDs as Python `int`; use `str(j.job_id) == "..."` for robust matching.

---

### Task 1: `us_stock_rows()` + `get_us_stocks()` in watchlists.py

**Files:**
- Modify: `src/pytvtools_core/watchlists.py` (append after `screen()`, end of file)
- Test: `tests/test_watchlists.py` (append a `TestUSStocks` class)

**Interfaces:**
- Consumes: `screen(market="america", exchange=str|None, columns=("name",)) -> (rows, total)` from the same module (already implemented).
- Produces: `us_stock_rows(market: str = "america", exchanges: tuple[str, ...] = ("NYSE", "NASDAQ", "AMEX")) -> list[dict[str, str]]` and `get_us_stocks(*, force_refetch: bool = False) -> Watchlist` (name `"US Stocks"`). Watchlist key/special-case string is `"US_STOCKS"`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_watchlists.py`:

```python
class TestUSStocks:
    @staticmethod
    def _fake_urlopen(responses):
        seq = iter(responses)

        def _open(req, timeout=None):
            return io.BytesIO(json.dumps(next(seq)).encode())

        return _open

    def test_us_stock_rows_unions_exchanges(self):
        responses = [
            {"totalCount": 2, "data": [{"s": "NYSE:A", "d": ["A"]},
                                      {"s": "NYSE:B", "d": ["B"]}]},
            {"totalCount": 1, "data": [{"s": "NASDAQ:COST", "d": ["COST"]}]},
            {"totalCount": 0, "data": []},
        ]
        with mock.patch("urllib.request.urlopen",
                        side_effect=self._fake_urlopen(responses)):
            rows = us_stock_rows(exchanges=("NYSE", "NASDAQ", "AMEX"))
        assert [r["symbol"] for r in rows] == ["NYSE:A", "NYSE:B", "NASDAQ:COST"]
        for r in rows:
            assert set(r) == {"symbol", "watchlist", "source"}
            assert r["watchlist"] == "US_STOCKS"
            assert r["source"] == "screen"

    def test_us_stock_rows_sends_exchange_filter_per_call(self):
        seen = []

        def _open(req, timeout=None):
            body = json.loads(req.data.decode())
            seen.append(body["filter"])
            return io.BytesIO(json.dumps({"totalCount": 1, "data": [
                {"s": "NASDAQ:T", "d": ["T"]}]}).encode())

        with mock.patch("urllib.request.urlopen", side_effect=_open):
            rows = us_stock_rows(exchanges=("NASDAQ",))
        assert seen == [[{"left": "exchange", "operation": "equal",
                          "right": "NASDAQ"}]]
        assert rows[0]["symbol"] == "NASDAQ:T"

    def test_get_us_stocks_returns_prefixed_watchlist(self):
        # get_us_stocks() calls us_stock_rows() -> one scanner call per exchange
        responses = [
            {"totalCount": 1, "data": [{"s": "NYSE:XOM", "d": ["XOM"]}]},
            {"totalCount": 0, "data": []},  # NASDAQ
            {"totalCount": 0, "data": []},  # AMEX
        ]
        with mock.patch("urllib.request.urlopen",
                        side_effect=self._fake_urlopen(responses)):
            wl = get_us_stocks()
        assert wl.name == "US Stocks"
        assert wl.symbols == ("NYSE:XOM",)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_watchlists.py::TestUSStocks -q`
Expected: FAIL — `ImportError: cannot import name 'us_stock_rows'`

- [ ] **Step 3: Write minimal implementation**

Append to the end of `src/pytvtools_core/watchlists.py` (after `screen()`):

```python
US_STOCK_EXCHANGES: tuple[str, ...] = ("NYSE", "NASDAQ", "AMEX")

_US_STOCKS_CACHE: Watchlist | None = None


def us_stock_rows(
    market: str = "america",
    exchanges: tuple[str, ...] = US_STOCK_EXCHANGES,
) -> list[dict[str, str]]:
    """One (symbol, US_STOCKS, screen) entry per listed US stock.

    Queries the TradingView scanner per exchange and unions the results.
    Symbols are already exchange-prefixed (``NYSE:A``), matching the
    format the cache/refresh path consumes.
    """
    rows: list[dict[str, str]] = []
    for exch in exchanges:
        screen_rows, _ = screen(market=market, exchange=exch)
        for r in screen_rows:
            rows.append({
                "symbol": str(r["symbol"]),
                "watchlist": "US_STOCKS",
                "source": "screen",
            })
    return rows


def get_us_stocks(*, force_refetch: bool = False) -> Watchlist:
    """Return a Watchlist of all listed US stocks (mirrors get_sp500).

    Cached in memory for process lifetime.  Raises on failure — unlike
    S&P 500 there is no static fallback snapshot for the whole market.
    """
    global _US_STOCKS_CACHE
    if _US_STOCKS_CACHE is not None and not force_refetch:
        return _US_STOCKS_CACHE
    symbols = tuple(r["symbol"] for r in us_stock_rows())
    _US_STOCKS_CACHE = Watchlist(name="US Stocks", symbols=symbols)
    return _US_STOCKS_CACHE
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_watchlists.py::TestUSStocks -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the full watchlists suite**

Run: `python3 -m pytest tests/test_watchlists.py -q`
Expected: PASS (37 passed — 34 existing + 3 new)

- [ ] **Step 6: Commit**

```bash
git add src/pytvtools_core/watchlists.py tests/test_watchlists.py
git commit -m "feat(core): add us_stock_rows() and get_us_stocks() from TradingView scanner"
```

---

### Task 1A (amend, discovered at Task 7 execution): stable `sort` in `screen()` pagination

**Files:**
- Modify: `src/pytvtools_core/watchlists.py` (the `screen()` function — add a `sort_by` parameter and include a `sort` block in the payload)
- Test: `tests/test_watchlists.py` (extend/add directly; a `TestScreenSort` class or assertion on the `screen` payloads)

**Why:** Task 7's registry run fetched only 3773/5701 distinct US symbols. Root cause: TradingView's scanner default order is **not stable across page requests**, so the `range [offset, offset+page_size]` pagination in `screen()` drifts — duplicates and missing symbols. Verified live: with no `sort`, the first page returns `['NYSE:DHI','NYSE:KEYS','NYSE:PRKS']` but with `sort {"sortBy":"name","sortOrder":"asc"}` it returns `['NYSE:A','NYSE:AA','NYSE:AADX']`, and a full paginated scan with `sortBy: name` gives **exact** counts: NYSE 2127, NASDAQ 3321, AMEX 253 (all distinct = 5701).

- [ ] **Step 1: Write the failing test**

In `tests/test_watchlists.py` add a test that asserts `screen()` sends a stable `sort` in the payload. It can reuse the existing mocked `urlopen` pattern from `TestScreen`:

```python
def test_screen_sends_stable_sort(self):
    seen = {}

    def _open(req, timeout=None):
        body = json.loads(req.data.decode())
        seen["sort"] = body.get("sort")
        seen["filter"] = body.get("filter")
        return io.BytesIO(json.dumps(
            {"totalCount": 1, "data": [{"s": "NYSE:A", "d": ["A"]}]}).encode())

    with mock.patch("urllib.request.urlopen", side_effect=_open):
        screen(exchange="NYSE")
    assert seen["filter"] == [{"left": "exchange", "operation": "equal",
                               "right": "NYSE"}]
    assert seen["sort"] == {"sortBy": "name", "sortOrder": "asc"}
```

Also extend `TestUSStocks.test_us_stock_rows_sends_exchange_filter_per_call` to assert the `sort` key is present in each request body (optional but cheap).

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_watchlists.py -q`
Expected: the new sort test FAILS (payload has no `sort` key); existing tests pass.

- [ ] **Step 3: Modify `screen()`**

Add a `sort_by: str | None = "name"` parameter to `screen(...)` and insert the sort block into `payload` before `range`:

```python
        payload: dict[str, object] = {
            "symbols": {"query": {"types": list(types)}},
            "columns": list(columns),
        }
        if sort_by:
            payload["sort"] = {"sortBy": sort_by, "sortOrder": "asc"}
        payload["range"] = [offset, offset + page_size]
```

Docstring: note that a stable sort (rising or default `"name"`) is required for correct pagination; `sort_by=None` disables it only for callers who know the server returns a stable order.

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest tests/test_watchlists.py -q`
Expected: PASS (38 passed — 37 existing + 1 new). Output pristine.

- [ ] **Step 5: Live spot-check (optional but recommended)**

Run the full-paginated scan with `sortBy: name` for NYSE/NASDAQ/AMEX and confirm fetched == distinct == totalCount (2127/3321/253). (Not a commit requirement; used to confirm before re-running the registry.)

- [ ] **Step 6: Commit**

```bash
git add src/pytvtools_core/watchlists.py tests/test_watchlists.py
git commit -m "fix(core): stable sort in screen() pagination for exact scans"
```

**Downstream effect:** after this lands and is synced/pushed/force-synced, **repeat the Task 7 registry rebuild**. Keep Tasks 8-9 as-is (their verification queries stay valid — they now expect US_STOCKS ≈ 5701, distinct total ≈ 6350).

---

### Task 2: Registry builder unions US stocks

**Files:**
- Modify: `notebooks/cache_registry.py`

**Interfaces:**
- Consumes: `us_stock_rows()` from Task 1; `registry_rows()` existing; `_CATALOG`, `_SCHEMA` from `pytvtools_core.cache`.
- Produces: registry table with additional `US_STOCKS`/`screen` rows; printed summary includes the `US_STOCKS` bucket.

- [ ] **Step 1: Edit the entries builder**

In `notebooks/cache_registry.py`, replace the block:

```python
# 1. build (symbol, watchlist, source) entries - all watchlists + S&P 500
entries = registry_rows()
print(f"Registry entries: {len(entries)}")
```

with:

```python
# 1. build (symbol, watchlist, source) entries - all watchlists + S&P 500 + US stocks
from pytvtools_core.watchlists import registry_rows, us_stock_rows

entries = registry_rows() + us_stock_rows()
print(f"Registry entries: {len(entries)} ({sum(1 for r in entries if r['source'] == 'screen')} from screen)")
```

- [ ] **Step 2: Add US_STOCKS summary line**

In the final summary block of `notebooks/cache_registry.py`, after the existing "Top watchlists" `show(...)`, append:

```python
print("US_STOCKS bucket:")
spark.sql(
    f"SELECT count(DISTINCT symbol) AS n FROM {OUTPUT_TABLE} "
    f"WHERE watchlist = 'US_STOCKS'"
).show(truncate=False)
```

- [ ] **Step 3: Verify locally (static check)**

Run: `python3 -c "import ast; ast.parse(open('notebooks/cache_registry.py').read())"`
Expected: no syntax errors. (Notebook is Databricks-only; no local execution.)

- [ ] **Step 4: Commit**

```bash
git add notebooks/cache_registry.py
git commit -m "feat(notebooks): registry builder includes US stocks from scanner"
```

---

### Task 3: `cache_refresh.py` — concurrency widget + US_STOCKS fallback

**Files:**
- Modify: `notebooks/cache_refresh.py`

**Interfaces:**
- Consumes: `get_us_stocks()` from Task 1; `MarketDataCache.refresh_multi_all` / `refresh_multi` with `max_concurrent` param.
- Produces: `concurrency` widget (string, default `"1"`); `watchlist == "US_STOCKS"` handled in the fallback branch.

- [ ] **Step 1: Add the concurrency widget**

In `notebooks/cache_refresh.py`, after the existing widget declarations:

```python
dbutils.widgets.text("concurrency", "1")
```

Then, where `MAX_CONCURRENT` is set, compute it from the widget:

```python
concurrency = max(1, int(dbutils.widgets.get("concurrency")))
```

Replace both `MAX_CONCURRENT = 1 if is_single else 1` lines (line ~100 and ~107) with `MAX_CONCURRENT = concurrency`. Update the print lines that mention `MAX_CONCURRENT` to use the variable. (Leave `BATCH_SIZE`, `CHUNK_SIZE`, sleeps unchanged — rate-limit safety.)

- [ ] **Step 2: Handle US_STOCKS in the fallback branch**

In the `elif watchlist:` fallback (registry missing/empty path), replace:

```python
    elif watchlist:
        wl = get_sp500() if watchlist == "SP500" else get_watchlist(watchlist)
```

with:

```python
    elif watchlist:
        if watchlist == "SP500":
            wl = get_sp500()
        elif watchlist == "US_STOCKS":
            wl = get_us_stocks()
        else:
            wl = get_watchlist(watchlist)
```

- [ ] **Step 3: Update the import guard + docstring**

Extend the `try/except ImportError` block so `get_us_stocks` is imported alongside `get_sp500, get_watchlist`:

```python
    try:
        from pytvtools_core.watchlists import get_sp500, get_watchlist, get_us_stocks
    except ImportError:
        get_sp500, get_watchlist, get_us_stocks = None, None, None
```

Add `US_STOCKS` to the docstring's available-watchlists line:
`CRYPTO, METALS_MINERS, INDEX_FUTURES, INDEX_CFDS, INDEX_ETFS, BONDS, OIL, URANIUM_STRATEGIC, US_STOCKS.`

- [ ] **Step 4: Verify static correctness**

Run: `python3 -c "import ast; ast.parse(open('notebooks/cache_refresh.py').read())"`
Expected: no syntax errors. Also grep to confirm no hardcoded `MAX_CONCURRENT = 1` remains:
`grep -n "MAX_CONCURRENT" notebooks/cache_refresh.py`
Expected: only `MAX_CONCURRENT = concurrency` lines.

- [ ] **Step 5: Commit**

```bash
git add notebooks/cache_refresh.py
git commit -m "feat(notebooks): add concurrency widget + US_STOCKS fallback to cache refresh"
```

---

### Task 4: Sync to core and push

**Files:** (no source edits — sync only)

- [ ] **Step 1: Sync**

Run: `python3 scripts/sync_core.py ../pytvtools-core-public --commit "feat(core): add us_stock_rows() and US stocks registry/refresh support"`
Expected: copies `src/pytvtools_core/watchlists.py`, `tests/test_watchlists.py`, `notebooks/cache_registry.py`, `notebooks/cache_refresh.py`; commits to the public repo.

- [ ] **Step 2: Push public core**

Run: `git -C ../pytvtools-core-public push`
Expected: `main -> main` push succeeds.

- [ ] **Step 3: Verify tests in the standalone repo**

Run: `cd /home/ilya/github/pytvtools-core-public && python3 -m pytest tests/test_watchlists.py -q`
Expected: PASS (37 passed) — the synced copy must run its own tests (`pythonpath=["src"]` is in the generated pyproject).

- [ ] **Step 4: Confirm main-repo commits are in place and push**

The main repo (`/home/ilya/github/pytvtools`, branch `main`) already holds Tasks 1–3 commits and the design spec commit. Confirm they exist:

```bash
cd /home/ilya/github/pytvtools
git log --oneline -6
git status --short
```

Expected: the last few commits are the spec, Task 1, Task 2, Task 3 work; `git status` clean (the sync script does NOT commit to the main repo — it only commits inside the public repo). Then push:
`git push origin main`

---

### Task 5: Force-sync the Databricks workspace git folder

**Files:** (none — SDK operation)

- [ ] **Step 1: Force-sync the workspace repo**

Run (from `PYTHONPATH=/tmp/opencode/dbsite`):

```python
from databricks.sdk import WorkspaceClient
ws = WorkspaceClient(profile="DEFAULT")
ws.repos.update(repo_id=2757908263996995, branch="main", dangerously_force_discard_all=True)
r = ws.repos.get(repo_id=2757908263996995)
print(r.head_commit_id)
```

- [ ] **Step 2: Verify the new code landed in the workspace git folder**

Fetch `watchlists.py` from the workspace repo and confirm the new symbols exist (the export body is **base64**, decode it):

```python
import base64
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.workspace import ExportFormat
ws = WorkspaceClient(profile="DEFAULT")
ex = ws.workspace.export(
    path="/Users/sl.ilya1987@gmail.com/pytvtools-core/src/pytvtools_core/watchlists.py",
    format=ExportFormat.SOURCE,
)
src = base64.b64decode(ex.content).decode()
assert "def us_stock_rows(" in src
assert "def get_us_stocks(" in src
print("OK")
```

Expected: `OK`.

---

### Task 6: Job templates — timeout + git_source fix

**Files:**
- Modify (in public-core repo, NOT main): `jobs/cache_refresh_daily.json`, `jobs/cache_refresh_weekly.json`, `jobs/cache_refresh_monthly.json`, `jobs/cache_refresh_on_demand.json`

- [ ] **Step 1: Edit templates**

In `cd /home/ilya/github/pytvtools-core-public`:
1. In `cache_refresh_daily/weekly/monthly.json` set `settings.tasks[0].timeout_seconds = 21600` and fix `settings.git_source` to `git_url: "https://github.com/ilyavs/pytvtools-core"`, `git_branch: "main"`.
2. In `cache_refresh_on_demand.json` set `settings.tasks[0].timeout_seconds = 21600` (no `git_source` — it is workspace-notebook based).

- [ ] **Step 2: Commit + push the public repo**

```bash
cd /home/ilya/github/pytvtools-core-public
git add jobs/
git commit -m "chore(jobs): raise cache refresh timeout to 6h, fix git_source to pytvtools-core@main"
git push
```

- [ ] **Step 3: Re-apply template configs to live jobs**

Update live jobs in the SDK to match the templates (timeout on all four; git_source on the three scheduled ones — verify it stays `ilyavs/pytvtools-core @ main`). Use `ws.jobs.update(job_id=..., new_settings=...)` with full task settings. Then verify each:

```python
from databricks.sdk import WorkspaceClient
ws = WorkspaceClient(profile="DEFAULT")
for jid, name in [(795017445883903, "daily"), (936004519313878, "weekly"),
                  (495785726036702, "monthly"), (646435410260973, "on_demand")]:
    for j in ws.jobs.list():
        if str(j.job_id) == str(jid):
            gs = j.settings.git_source
            print(name, "timeout", j.settings.tasks[0].timeout_seconds,
                  "git", gs.git_url + "@" + gs.git_branch if gs else "none")
```

Expected: all four show `timeout 21600`; the three scheduled show `https://github.com/ilyavs/pytvtools-core @ main`; on-demand shows `none` git.

---

### Task 7: Rebuild the symbol registry

**Files:** (none — runs the synced notebook as a job)

- [ ] **Step 1: Trigger the registry build**

Run the `cache_registry` notebook via `ws.jobs.run_now` on the on-demand job **or** run the notebook by path. Simplest reliable path: use the existing job mechanism if present, else `ws.workspace` isn't for executions — use `ws.jobs.run_now(job_id=...)` only if a registry job exists; otherwise create a throwaway run. Preferred concrete step — run the notebook through the Jobs API by creating a one-off job pointing at `/Users/sl.ilya1987@gmail.com/pytvtools-core/notebooks/cache_registry` (source WORKSPACE), run it, delete it. (Check first: `for j in ws.jobs.list(): if 'cache_registry' in j.settings.name: print(j.job_id)`.)

- [ ] **Step 2: Verify the registry content**

Run:

```sql
SELECT watchlist, count(*) n FROM workspace.chartdata.symbol_registry GROUP BY watchlist ORDER BY n DESC;
SELECT count(*) FROM (SELECT DISTINCT symbol FROM workspace.chartdata.symbol_registry);
SELECT count(DISTINCT symbol) FROM workspace.chartdata.symbol_registry WHERE watchlist = 'US_STOCKS';
```

Expected: `US_STOCKS` ≈ 5701; distinct total ≈ 6350 (650 existing + 5701, minus overlap with SP500/watchlists); `source='screen'` rows present.

- [ ] **Step 3: Commit note** (no code change — skip commit)

---

### Task 8: Backfill 1D/1W/1M via the on-demand job

**Files:** (none — job runs)

- [ ] **Step 1: Run backfill for each timeframe**

For each `tf in ("1D", "1W", "1M")`, trigger `cache_refresh_on_demand` (`646435410260973`) with `mode=backfill`, `watchlist=US_STOCKS`, `timeframe=tf`, `concurrency=1`. Run them **sequentially** (rate-limit safety). e.g.

```python
from databricks.sdk import WorkspaceClient
ws = WorkspaceClient(profile="DEFAULT")
r = ws.jobs.run_now(job_id=646435410260973,
                    notebook_params={"timeframe": "1D", "mode": "backfill",
                                     "watchlist": "US_STOCKS", "concurrency": "1"})
print(r.run_id)
```

Then poll `ws.jobs.get_run(run_id=r.run_id).state` until `TERMINATED` / `SKIPPED`, logging `run_page_url`. Expect **hours** per timeframe. Move to the next timeframe only after the previous run completes (concurrency 1; do not parallelize).

- [ ] **Step 2: Monitor and record outcomes**

For each run, record `state.result_state` and `state.life_cycle_state`; if a run failed, fix and re-run that timeframe only.

- [ ] **Step 3: Verify the cache table after each timeframe backfill**

```sql
SELECT timeframe, count(*) n, count(DISTINCT symbol) syms,
       min(timestamp) earliest, max(timestamp) latest
FROM workspace.chartdata.ohlcv GROUP BY timeframe ORDER BY timeframe;
SELECT count(*) FROM (
    SELECT DISTINCT symbol FROM workspace.chartdata.ohlcv
    WHERE timeframe IN ('1D','1W','1M'));
```

Expected: `syms` ≈ 6350 across timeframes; 1D row count ≫ 5.5M (≈9× at ~50M); 1W ≫ 1.1M; 1M ≫ 269K. Spot-check known tickers:

```sql
SELECT symbol, count(*) n, min(timestamp), max(timestamp)
FROM workspace.chartdata.ohlcv
WHERE symbol IN ('NASDAQ:AAPL', 'NYSE:BRK/B', 'NYSE:XOM', 'NYSE:BA', 'NASDAQ:SMCI')
GROUP BY symbol ORDER BY symbol;
```

Expected: each has rows with sensible first (e.g. AAPL 1980-ish) and last (recent) dates.

---

### Task 9: Final verification

**Files:** (none)

- [ ] **Step 1: Confirm no rate-limit regressions**

Check a sample of recent job run logs from the backfill runs (`ws.jobs.get_run` + `workspace.export` of run log/sstderr if needed) for the scrollback of "All connection attempts failed" style errors in clusters; confirm failures ≈ 0 across the total.

- [ ] **Step 2: Confirm the whole universe landed**

```sql
SELECT count(DISTINCT symbol) FROM workspace.chartdata.ohlcv WHERE timeframe = '1D';
SELECT count(*) FROM workspace.chartdata.symbol_registry WHERE source = 'screen';
SELECT count(*) FROM workspace.chartdata.symbol_registry WHERE watchlist = 'US_STOCKS';
```

Expected: 1D distinct symbols ≈ registry `US_STOCKS` distinct + existing; screen rows ≈ 5701.

- [ ] **Step 3: Update the progress ledger**

Append a dated entry to `.superpowers/sdd/2026-08-08-symbol-registry/progress.md` summarizing: registry updated (~6350 distinct), backfill run per timeframe with row counts, verification results, and the job-config changes (timeout/git_source).