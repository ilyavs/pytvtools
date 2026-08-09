# US Stocks into `ohlcv` (1D/1W/1M) via symbol registry — design

Date: 2026-08-09

## Goal

Load **all US-listed stocks** (~5701: NYSE 2127 + NASDAQ 3321 + AMEX 253) into the
existing market-data cache table `workspace.chartdata.ohlcv` with full-history
1D, 1W, and 1M bars, driven by the same registry → scheduled-job pipeline used
for the VIX ingest and the existing watchlist refresh.

## Decisions (approved interactively)

1. **Target table** = `workspace.chartdata.ohlcv` (the existing cache the
   daily/weekly/monthly jobs write into). No new table.
2. **Universe** = listed stocks on the 3 major US exchanges only (NYSE, NASDAQ,
   AMEX). Excludes OTC (~6083 names) — illiquid shells, sparse data, churn.
3. **History depth** = full backfill (every bar TV returns), matching how the
   existing 646 symbols were loaded (`refresh_multi_all` pagination).
4. **How US stocks enter the registry** = `screen()` (the scanner API we added)
   feeds the registry *at build time* (Approach A), rather than a static blob of
   5701 symbols in source.
5. **Execution** = one-off backfill through the existing on-demand job (3 runs,
   one per timeframe) at conservative concurrency; then the 3 scheduled jobs
   sweep the bigger registry on their normal cadence.
6. **Rate limits trump speed** — keep concurrency 1 (configurable), jittered
   sleeps, retry-with-backoff intact. No tuning for speed.

## Current state

- `symbol_registry`: 650 distinct symbols from 12 watchlists + SP500.
- `ohlcv`: 1D ≈ 5.5M rows / 647 syms; 1W ≈ 1.1M; 1M ≈ 269K.
- Live jobs: daily `795017445883903` (1D), weekly `936004519313878` (1W),
  monthly `495785726036702` (1M), on-demand `646435410260973`. All read symbols
  from `symbol_registry` (`SELECT DISTINCT symbol`) and write to `ohlcv`.
- Live jobs' `git_source` = `ilyavs/pytvtools-core @ main` (correct).
- Repo job templates (`jobs/cache_refresh_*.json`) carry the documented
  regression: `git_url: ilyavs/pytvtools-core-public @ master` (a "public" repo
  at `master` that does not exist). Must be fixed when re-applying job configs.

## Design

### Section 1 — `src/pytvtools_core/watchlists.py`

Add, next to `screen()`:

```python
US_STOCK_EXCHANGES = ("NYSE", "NASDAQ", "AMEX")

def us_stock_rows(market: str = "america",
                  exchanges: tuple[str, ...] = US_STOCK_EXCHANGES) -> list[dict[str, str]]:
    """One {symbol, watchlist: "US_STOCKS", source: "screen"} row per listed US stock."""

def get_us_stocks(*, force_refetch: bool = False) -> Watchlist:
    """Lazy Watchlist of all listed US stocks (mirrors get_sp500)."""
```

Behavior:
- `us_stock_rows()` calls `screen(market=market, exchange=exch)` for each
  exchange in sequence and unions the rows. Symbols come back already
  exchange-prefixed (`NYSE:A`, `NASDAQ:AAPL`) — exactly what the cache/refresh
  path consumes via `_candidates`.
- `get_us_stocks()` caches in a module-level `_US_STOCKS_CACHE`; on failure
  raises (no static fallback needed — unlike SP500, this universe is only
  reachable live; registry present in Databricks so fallback rarely hit).
- Watchlist name is `"US Stocks"`; catalog key `"US_STOCKS"`.

Tests (`tests/test_watchlists.py`): reuse the mocked-`urlopen` pattern from
`TestScreen` to assert:
- unioned count matches the exchange totals (mock small totals, e.g. 2/1/1)
- row keys `{symbol, watchlist: "US_STOCKS", source: "screen"}`
- exchange filter is sent top-level per exchange call
- `get_us_stocks()` returns a `Watchlist` with prefixed symbols

### Section 2 — Notebooks

`notebooks/cache_registry.py`:
- `entries = registry_rows() + us_stock_rows()`
- add a summary print: `US_STOCKS` row count (e.g. `SELECT watchlist, count(*) ... WHERE watchlist='US_STOCKS'`).

`notebooks/cache_refresh.py`:
- In the registry-missing/empty fallback path, special-case
  `watchlist == "US_STOCKS"` → `get_us_stocks()` (mirrors `SP500`).
- With registry present, `WHERE watchlist='US_STOCKS'` already works — no change.

### Section 3 — Backfill & job config (rate-limit-safe)

`notebooks/cache_refresh.py`:
- Add a `concurrency` widget, **default `1`** (current behavior), applied to
  `MAX_CONCURRENT` in both `refresh_multi_all` and `refresh_multi`. Batch size
  and jittered sleeps unchanged.
- `"US_STOCKS"` added to the docstring's available-watchlists list.

One-off backfill (existing on-demand job `646435410260973`):
- 3 runs: `{timeframe: "1D"|"1W"|"1M", mode: "backfill", watchlist: "US_STOCKS", concurrency: "1"}`.
- Runtime is expected to be many hours per timeframe (≈9× the existing
  646-symbol backfill) — acceptable; no speed tuning.

Timeout:
- Raise `timeout_seconds` 3600 → **21600 (6h)** on all four cache-refresh jobs
  (daily/weekly/monthly/on-demand) so long sweeps aren't killed. Reliability,
  not speed.

Templates:
- Fix `jobs/cache_refresh_{daily,weekly,monthly}.json` `git_source` to
  `https://github.com/ilyavs/pytvtools-core @ main`.
- Re-apply job configs to live jobs via API (git_source, timeout), matching
  templates.

### Verification

- Registry rebuild: distinct symbols ≈ 6350 (650 existing + 5701 US — some
  overlap with existing watchlists/SP500 is expected); `US_STOCKS` count ≈ 5701.
- Post-backfill `ohlcv` checks per timeframe: distinct symbols ≈ 6350;
  spot-check known tickers (`NASDAQ:AAPL`, `NYSE:BRK/B`, `NYSE:XOM`,
  `NYSE:BA`, small caps) have bars and sensible first/last dates.
- `cache_refresh` fallback path unit-tested (mocked `get_us_stocks`).