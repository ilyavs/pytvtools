# Cap-Weighted Index Construction — Design

## Goal

A reusable **cap-weighted index** building block for the absorption-ratio
reproduction (Kritzman et al. 2011), which needs industry-level return series
built from S&P 500 members grouped by GICS industry.

Two deliverables this iteration:

1. `cap_weighted_index()` — a pure-numpy core function that turns member close
   series + static market caps into a cap-weighted index level series,
   handling per-date member availability (new listings ramp in, never truncate).
2. A date-stamped `workspace.chartdata.market_caps` UC table, refreshed on
   demand, from which cap weights are read.

The AR reproduction itself (building 69 GICS-industry indexes + running AR on
them) is a **follow-up iteration** — this spec covers only the building block.

## Decisions (from brainstorming)

| Question | Decision |
|----------|----------|
| Feature shape | **A** — pure-numpy `cap_weighted_index()` in `measures.py` + `get_market_caps()` in `watchlists.py` + builder notebook |
| Scope | Core function + date-stamped market_caps table + refresh, all now |
| Cap weights | Static as-of snapshot date (one scanner call per refresh); time-varying caps out of scope |
| Member availability | Per-date renormalization — a member contributes only on dates it has data; index spans the **oldest** available member, never truncated by the youngest |
| Trimming | At the index level only (drop an index whose own series is too short) — never per-stock; AR iteration decides the cutoff |
| Cap source | `market_cap_basic` column via scanner **ticker-list** query (verified: AAPL $4.46T, BRK.B $971B) |
| Refresh | Manual-first notebook, no scheduled job (same stance as `cache_classifications`) |

## Data source

| Source | Field | Refresh |
|--------|-------|---------|
| TradingView scanner (`https://scanner.tradingview.com/america/scan`) | `market_cap_basic` | on demand via notebook |

The existing `screen()` only does **filter/query** style (`symbols.query`). A
ticker-list query (`symbols.tickers`) is a different POST shape and returns
caps for an explicit symbol list — `get_market_caps()` implements it fresh,
mirroring `screen()`'s urllib conventions (UA/Referer headers, error wrapping).

## Architecture

### Component 1 — `cap_weighted_index()` in `src/pytvtools_core/measures.py`

Pure-numpy, appended to the existing AR module (numpy imported inside the
function, same as `absorption_ratio`). No pandas, no network.

```python
def cap_weighted_index(
    closes: Any,              # (T, N) np.ndarray; NaN = member not trading that day
    caps: Any,                # (N,) np.ndarray; static market caps (as-of snapshot)
    base: float = 100.0,      # index level at the first date with any available member
) -> Any:                     # (T,) np.ndarray index levels; NaN for leading all-empty rows
    """Cap-weighted index level series from member closes + static caps."""
```

**Algorithm** (per-date availability, renormalized weights):

- On each date `t`, the available set = members with a non-NaN close that day.
  Weight of member `i` on day `t` = `caps[i] / Σ caps[available on t]` — weights
  always sum to 1.
- Index return from `t-1 → t` uses members with data on **both** days:
  `R_t = Σ_i w_i(t) · (close_i(t)/close_i(t-1) − 1)` over members valid on both.
  A member's first trading day has no `t-1` close, so it **ramps in from the
  next day** (its weight participates once it has a return).
- Levels chain: `L_t = L_{t-1} · (1 + R_t)`, starting `L = base` at the first
  date with any available member. Rows before that stay NaN.

Guarantees:
- A short-history member never truncates the series — it sits out its missing
  years; the index spans the oldest member with data.
- Renormalization means the index is a valid cap-weighted portfolio every day.

### Component 2 — `get_market_caps()` in `src/pytvtools_core/watchlists.py`

```python
def get_market_caps(
    symbols: list[str],       # explicit ticker list (bare or prefixed)
    market: str = "america",
    timeout: float = 30.0,
) -> dict[str, float]:
    """Market caps for an explicit ticker list via scanner `market_cap_basic`.

    Returns {symbol: cap} keyed exactly as the caller passed each symbol.
    """
```

- POST `{"symbols": {"tickers": [...]}, "columns": ["market_cap_basic"], "range": [0, len]}`.
  No `sort` needed (ticker-list results have a stable per-ticker order).
- Single request (the ticker list is ~503 symbols; the scanner accepts a large
  explicit list). If response truncates (defensive), paginate in chunks like
  `screen()`.
- Reuses `screen()`'s UA/Referer headers and error-wrapping style; raises
  `RuntimeError` on HTTP failure (no static fallback — same stance as
  `get_us_stocks`).
- Null caps (delisted / non-tradable) come back as `None` → dropped from the
  result (consumer decides; dropping matches cap-weighted semantics).

### Component 3 — `notebooks/cache_market_caps.py`

Mirrors `notebooks/cache_classifications.py` (cell markers, `%pip install`,
`sys.path.insert`, `_CATALOG`/`_SCHEMA` imports):

1. Resolve S&P 500 members (`get_sp500()`).
2. `caps = get_market_caps(list(members))`.
3. Tag `snapshot_date = datetime.now(timezone.utc).date()`.
4. **Append** rows `{symbol, market_cap, snapshot_date}` to
   `workspace.chartdata.market_caps` — keeps history so future iterations can
   use time-varying caps. To keep same-day re-runs idempotent, `DELETE FROM
   ... WHERE snapshot_date = today` before inserting.
5. Print per-run summary (count, sample).

**Schema** (`workspace.chartdata.market_caps`):

| column | type | example |
|--------|------|---------|
| `symbol` | STRING | `NASDAQ:AAPL` (form as passed to `get_market_caps`) |
| `market_cap` | DOUBLE | 4460000000000.0 |
| `snapshot_date` | DATE | `2026-08-15` |

Consumers pick the latest snapshot:
```sql
SELECT symbol, market_cap FROM workspace.chartdata.market_caps
WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM workspace.chartdata.market_caps)
```

## Sequence

1. Implement + test `cap_weighted_index()` (`tests/test_measures.py`).
2. Implement + test `get_market_caps()` (`tests/test_watchlists.py`, urllib mocked).
3. Write `notebooks/cache_market_caps.py`.
4. Add to `sync_core.py` `CORE_NOTEBOOKS`.
5. Run the full local test suite.
6. Sync + push to the core repo.
7. Run the notebook in Databricks manually → `market_caps` table exists.

## Testing

`tests/test_measures.py` (numpy already a dep):
- Single member → output equals that member's price, scaled to `base` at the
  first valid date.
- Two equal-cap members, one listed late → late joiner ramps in, series spans
  the older member (no truncation); weights renormalize while joiner absent.
- Weights sum to 1 on every date (renormalization invariant).
- Leading all-NaN rows → NaN; index starts at first valid row.
- Hand-computed small case (2 members, 3 dates) → exact expected levels.
- Caps with a `0` entry → zero-weight member (never divides by zero).

`tests/test_watchlists.py` (urllib mocked):
- Payload uses `symbols.tickers` (not `query`), includes `market_cap_basic`.
- Response maps `{symbol: cap}`; null caps dropped.
- HTTP error → `RuntimeError` with a clear message.

## Error handling

- `get_market_caps` network failure → `RuntimeError` (no static fallback).
- `cap_weighted_index`:
  - `closes` not 2-D / `caps` length mismatch → `ValueError`.
  - No member has data anywhere → `ValueError` (index undefined).
  - NaN **inside** an available member's series (not a listing gap) → treated
    as "not trading that day" (excluded from that day's return), consistent
    with per-date availability. No silent extrapolation.
- Notebook: `DELETE ... WHERE snapshot_date = today` guarded so a mid-run
  failure leaves the previous snapshot intact (delete only after fetch succeeds).

## Out of scope

- AR reproduction (building GICS-industry indexes + AR) — follow-up iteration.
- Time-varying cap weights (multiple snapshots used jointly).
- A scheduled refresh job for `market_caps` (manual-first).
- Joining `market_caps` to `classifications`/`symbol_registry` in one table.
