# Symbol Classifications (GICS + TradingView) — Design

## Problem

The absorption-ratio work (Kritzman et al. 2011) uses a universe of ~51 U.S.
**industry** return series from the MSCI USA index (GICS industry tier,
sourced via Datastream). MSCI industry series are not available on
TradingView. To reproduce the paper's universe from free data we need to:

1. Build industry-level return series from S&P 500 constituents grouped by
   GICS industry — requires a per-ticker GICS classification mapping.
2. Optionally cross-check with TradingView's own sector/industry taxonomy
   (ICB-style, returned by the scanner API).

Neither mapping is persisted anywhere in the repo or UC today.

## Goal

- A core module `pytvtools_core/classifications.py` (adjacent to
  `watchlists.py`) exposing:
  - `get_gics_classifications()` — per-ticker GICS sector / industry_group /
    industry / sub_industry with the four-tier roll-up already applied.
  - `get_tv_classifications()` — per-ticker TradingView sector/industry
    (ICB-style), via the existing `screen()`.
- A UC table `workspace.chartdata.symbol_classifications` — one row per
  `(symbol, taxonomy)` for both `gics` and `tv`.
- A builder notebook `notebooks/cache_classifications.py` (mirrors
  `cache_registry.py`), manual-first.
- Unit tests in `tests/test_classifications.py`, carried to the core repo by
  `sync_core.py`.

## Data sources

| Source | Universe | Taxonomy | Columns | Refresh |
|--------|----------|----------|---------|---------|
| `datasets/s-and-p-500-companies` `constituents.csv` (GitHub) | S&P 500 members (~503) | GICS | sector, sub_industry (as published) | quarterly (S&P membership) |
| `skysaint/gics-data` `en/gics.csv` (GitHub) | full GICS structure | GICS | code, name, parent_code, level_num (273 rows, 2023 ed.) | yearly |
| TradingView scanner API (via `screen()`) | all US stocks (NYSE/NASDAQ/AMEX) | ICB-style | sector, industry | live |

The GICS `constituents.csv` publishes only sector + sub-industry; the
**industry tier** (the paper's ~51-industry level) is derived by rolling
sub-industries up through the GICS hierarchy (74 industries / 25 industry
groups / 11 sectors in the 2023 edition). The 503 S&P 500 members resolve to
69 distinct GICS industries.

## Table schema

`workspace.chartdata.symbol_classifications` — one row per `(symbol, taxonomy)`:

| column         | type      | gics rows            | tv rows              |
|----------------|-----------|----------------------|----------------------|
| `symbol`       | STRING    | e.g. `NASDAQ:AAPL`   | e.g. `NASDAQ:AAPL`   |
| `taxonomy`     | STRING    | `gics`               | `tv`                 |
| `sector`       | STRING    | GICS sector          | TV sector (ICB)      |
| `industry_group` | STRING | GICS industry group  | NULL                 |
| `industry`     | STRING    | GICS industry (paper-level) | TV industry (ICB) |
| `sub_industry` | STRING    | GICS sub-industry    | NULL                 |
| `security`     | STRING    | company name         | NULL                 |
| `refreshed_at` | TIMESTAMP | run timestamp        | run timestamp        |

- A symbol appears twice: once `taxonomy='gics'`, once `taxonomy='tv'`.
- `industry_group` / `sub_industry` / `security` are NULL for TV rows (no
  fabricated data); `sector`/`industry` exist for both but from different
  taxonomies — consumers must filter on `taxonomy`.
- **Symbol form:** `symbol` is stored in the same form `ohlcv` stores
  (exchange-prefixed when resolvable, e.g. `NASDAQ:AAPL`). GICS symbols that
  cannot be matched to an exchange keep bare dash-form (matching
  `symbol_registry`'s S&P rows); TV symbols are always prefixed (as
  `screen()` returns them). Consumers joining to `ohlcv` should use the same
  prefix-fallback `MarketDataCache._candidates()` applies.
- **Write strategy:** full rebuild (`REPLACE TABLE`) each run — idempotent,
  no drift (same as `symbol_registry`).

## Components

### `src/pytvtools_core/classifications.py` (new)

Mirrors `watchlists.py` conventions (no new deps; stdlib + optional pandas
for CSV parsing, same as `get_sp500()`).

- `_GICS_HIERARCHY` — embedded dict `{code: {name, parent_code, level_num}}`
  for all 273 GICS codes (2023 edition). Vendored constant (Approach A),
  like `_SP500_TICKERS`.
- `_GICS_CONSTITUENTS_STATIC` — embedded ~503-row snapshot of
  `(symbol, security, sector, sub_industry)`, used only if the live fetch
  fails.
- `get_gics_classifications(*, force_refetch=False)`:
  1. Fetch `constituents.csv` from GitHub (pandas `read_csv`); on failure log
     and use `_GICS_CONSTITUENTS_STATIC`.
  2. Map each constituent's sub-industry name → code via a **level-4-only
     name index** (`_GICS_HIERARCHY` filtered to `level_num == '4'`). This is
     required because names collide across tiers (e.g. "Building Products" is
     both sub-industry `20102010` and industry `201020`).
  3. Walk `parent_code` chain: sub-industry → industry → industry group →
     sector. Any broken linkage raises a clear error (no silent drop).
  4. Normalize symbols to **dash form** (`.` → `-`, as `get_sp500()` does),
     then resolve the **exchange prefix** so the symbol matches how `ohlcv`
     stores it (resolved candidates like `NASDAQ:AAPL`, `NYSE:X`). Prefix is
     resolved by matching each bare symbol against the `screen()` symbol list
     (already fetched for the TV rows); unmatched symbols fall back to bare
     dash-form. This makes `symbol` joinable to `workspace.chartdata.ohlcv`.
  5. Return `[{symbol, security, sector, industry_group, industry, sub_industry}]`.
- `get_tv_classifications(*, market="america", exchanges=("NYSE","NASDAQ","AMEX"))`:
  reuse `screen()` to pull `sector` + `industry` columns per exchange
  (paginated), union, return `[{symbol, sector, industry}]` (symbols already
  exchange-prefixed). Raises on network failure (no static fallback for the
  whole market — same stance as `get_us_stocks`).
- `classification_rows()` — optional convenience that unions both sources and
  tags `taxonomy` (used by the notebook; keeps notebook thin like
  `registry_rows()` does for the registry).

### `notebooks/cache_classifications.py` (new)

Mirrors `notebooks/cache_registry.py`:

- `%pip install -q websockets`, `sys.path.insert(...)` to the core git folder.
- Widgets: `table` (default `workspace.chartdata.symbol_classifications`).
- Steps:
  1. `gics_rows = get_gics_classifications()` → tag `taxonomy='gics'`.
  2. `tv_rows = get_tv_classifications()` → tag `taxonomy='tv'`.
  3. `spark.createDataFrame(...)` → `REPLACE TABLE`.
  4. Print per-taxonomy counts + sample rows.

### `scripts/sync_core.py` (modified)

- `CORE_TESTS`: add `tests/test_classifications.py`.
- `CORE_NOTEBOOKS`: add `notebooks/cache_classifications.py`.
- `classifications.py` is under `src/pytvtools_core/` which is already copied
  whole-dir — no per-file change needed.

## Sequence

1. Implement + test `classifications.py` locally (`pytest tests/test_classifications.py`).
2. Run the sync to the core repo.
3. Deploy + run `cache_classifications.py` manually in Databricks → table
   exists. Verify per-taxonomy counts (GICS ~503, TV ~6-7k US stocks).
4. (Follow-up, out of scope) consumption in `absorption_ratio.py`.

## Error handling

- GICS live fetch failure → static snapshot + explicit log line (mirrors
  `get_sp500`).
- GICS hierarchy linkage break → raise (data corruption, don't silently skip).
- TV fetch failure → raise (no static fallback).
- Notebook: `REPLACE` only after both fetches succeed; mid-run failure leaves
  the previous table intact.

## Out of scope

- Consuming the classifications table in `absorption_ratio.py` (follow-up).
- Scheduled refresh job for the classifications table (manual-first, like
  `symbol_registry`).
- Other taxonomies (FTSE ICB, Datastream MSCI industry series).
- Joining classifications to `symbol_registry` in one table (they remain
  separate tables; join on `symbol` when needed).
