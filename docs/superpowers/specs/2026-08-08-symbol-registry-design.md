# Symbol Registry + Refresh Job — Design

## Problem

Three sources of staleness in `chartdata.ohlcv`:

- The scheduled `cache_refresh_{daily,weekly,monthly}` jobs only sweep the S&P 500
  (default watchlist). The ~11 static watchlists (SPDR, METALS_MINERS, INDEX_*,
  BONDS, OIL, URANIUM_STRATEGIC) are never refreshed by schedule, leaving ~120
  symbols stale since 2026-07-13/14.
- There is no single table that maps every cached ticker to its watchlist, or
  that records first/last data points per symbol.
- `cache_refresh.py` decides what to refresh locally from watchlist code; there
  is no persisted, queryable symbol list.

## Goal

- A **registry table** `workspace.chartdata.symbol_registry` storing one row per
  `(symbol, watchlist)` with `first_listed` and `last_updated` derived from
  `chartdata.ohlcv`.
- A **registry builder notebook** (`notebooks/cache_registry.py`) that aggregates
  ALL watchlists (static `WATCHLISTS` registry + S&P 500 via `get_sp500()`) and
  writes the registry.
- The **refresh job consumes the registry** — `cache_refresh.py` reads
  `SELECT DISTINCT symbol` from the registry and refreshes all of it. Missing /
  empty registry falls back to the current S&P 500 batch.

Built sequence is **manual-first**: build the registry, then migrate refresh jobs.

## Table schema

`workspace.chartdata.symbol_registry` — one row per `(symbol, watchlist)`:

| column        | type      | source |
|---------------|-----------|--------|
| `symbol`      | STRING    | watchlist symbol (e.g. `AMEX:GDX`) |
| `watchlist`   | STRING    | name (e.g. `SPDR_INDUSTRIES`) |
| `source`      | STRING    | `watchlist` (static) or `sp500` (dynamic) |
| `first_listed`| TIMESTAMP | `min(timestamp)` for symbol in `chartdata.ohlcv` |
| `last_updated`| TIMESTAMP | `max(timestamp)` for symbol in `chartdata.ohlcv` |

- A symbol in multiple watchlists (e.g. `SLX` in both `SPDR_INDUSTRIES` and
  `URANIUM_STRATEGIC`) gets multiple rows.
- `first_listed` / `last_updated` are computed over **all timeframes** of that
  symbol in `chartdata.ohlcv`, not per-timeframe.
- Symbols present in the watchlist but with no bars yet get a row with NULL
  timestamps (so the registry still lists them).
- **Write strategy:** full rebuild (`REPLACE TABLE`) each run — idempotent, no
  drift, no dedup complexity.

## Components

### `notebooks/cache_registry.py` (new)

Mirrors `notebooks/cache_refresh.py` conventions:

- `%pip install -q websockets`
- `sys.path.insert(0, "/Workspace/Users/sl.ilya1987@gmail.com/pytvtools-core/src")`
- Optional widgets: `table` (default `workspace.chartdata.symbol_registry`).
- Steps:
  1. Build `(symbol, watchlist, source)` rows:
     - iterate `WATCHLISTS` registry keys → `source="watchlist"`
     - `get_sp500()` → `source="sp500"`
  2. Read `chartdata.ohlcv` aggregated per symbol:
     `SELECT symbol, min(timestamp) AS first_listed, max(timestamp) AS last_updated FROM workspace.chartdata.ohlcv GROUP BY symbol`
  3. Left join watchlist(entries to aggregates on `symbol`.
  4. `REPLACE TABLE` via `spark.sql()` with the joined DataFrame (mode=spark).
  5. Print per-watchlist counts + a few sample rows for confirmation.

The registry is rebuilt wholesale (`REPLACE`), so no MERGE/dedup logic is
needed. Table identifiers reuse the `_CATALOG`/`_SCHEMA` constants pattern
from `pytvtools_core.cache`.

### `notebooks/cache_refresh.py` (modified)

Replace the symbol-resolution block (lines ~36–64):

1. Read registry (`spark.sql`):
   - If `symbol_registry` exists and has rows → `symbols = SELECT DISTINCT symbol`
     (optionally filtered by `watchlist` widget) `ORDER BY symbol`.
   - If 0 rows or table missing → log a clear warning and fall back to the
     current watchlist-resolution behavior:
     - `watchlist` widget set → resolve from code (`get_watchlist`/`get_sp500`).
     - no widget → S&P 500 batch (today's default).
2. Keep `timeframe`, `mode`, `symbol` widgets unchanged.
- The `watchlist` widget is kept: when the registry is present it acts as an
  **include filter on `symbol_registry.watchlist`** (all symbols of that
  watchlist); when absent it falls back to code-based resolution. Default (no
  widget) = refresh all registry rows.

No changes to the three job JSONs — the notebooks are the only edit.

## Sequence (manual build first)

1. Deploy and run `cache_registry.py` manually → registry table exists.
2. Deploy modified `cache_refresh.py` → next scheduled job run reads the
   registry automatically.

## Error handling

- Registry build: `REPLACE` only after the aggregate read succeeds; a mid-run
  failure raises and leaves the old logical table intact / no partial write.
- Refresh: registry missing/empty → safe fallback to S&P 500 so the pipeline
  never silently refreshes nothing; explicit warning logged.

## Out of scope

- Making the registry a scheduled job (not requested).
- Creating the other `tvdata`/`trading` tables or their notebooks.
- Changing job schedule/pause states.