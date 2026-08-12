# Absorption Ratio + SPX Chart — Design

## Goal

Compute the **absorption ratio** (AR) — the share of a universe's total return variance absorbed by a fixed number of principal components (Kritzman, Li, Page & Rigobon 2010) — from the cached OHLCV data in `workspace.chartdata.ohlcv`, and render it alongside the S&P 500 index using TradingView Lightweight Charts (via the existing `pytvtools_core.chart.Chart` generator).

## References

- **frds**: `AR = Σ(top-N eigenvariances) / Σ(all eigenvariances)` of the asset covariance matrix. Default `fraction_eigenvectors=0.2`.
- **portfoliooptimizer**: same definition; empirically recommends retaining **1 eigenvector** for simplicity; canonical universe = SPDR sector ETFs; 52-week window of weekly returns.

## Decisions (from brainstorming)

| Question | Decision |
|----------|----------|
| Universe | Parameter (widget); POC = 11 sector SPDR ETFs (`SPDR_SECTORS`) |
| Frequency/window | Parameter; compute BOTH canonical variants (daily/500d + weekly/52w) |
| Eigenvectors kept | Parameter; default `1` (int count); float <1 = fraction (frds 0.2) |
| Chart layout | SPX candles (top pane) + AR lines (bottom pane), time-synced |
| Delivery | `displayHTML()` in-notebook AND save HTML copy to a UC volume |
| Code location | Core numpy function in `pytvtools_core` + orchestration in notebook |
| Approach | **A** — small tested core fn; notebook does data-load/align/plot |

## Architecture

### Component 1 — `pytvtools_core/measures.py` (new file, core package)

Pure-numpy absorption ratio. Imported inside functions to keep module import dependency-light; `numpy` added to the synced `pyproject.toml` deps.

```python
def absorption_ratio(
    returns: np.ndarray,               # (T, N) asset returns
    n_eigenvectors: int | float = 1,   # int count, or float <1 = fraction of assets
) -> float:
    """AR = Σ(top-n eigenvariances) / Σ(all eigenvariances) of the returns covariance."""

def rolling_absorption_ratio(
    closes: np.ndarray,                # (T, N) close matrix, row=date, col=asset
    window: int = 500,                 # rolling window in bars
    step: int = 1,                     # recompute every `step` bars
    n_eigenvectors: int | float = 1,
) -> tuple[np.ndarray, np.ndarray]:
    """Returns (windows_ts, ar_series): AR aligned to the END date of each window."""
```

Implementation notes:
- **Returns**: simple `pct_change` from closes (matches portfoliooptimizer's empirical covariance).
- **Covariance**: sample covariance `np.cov(rowvar=False)`; eigen via `np.linalg.eigvalsh` (symmetric fast path).
- **`n_eigenvectors`**: int = exact count; float <1 = `max(1, int(frac * N))`.
- **NaN policy**: rolling fn asserts no NaNs inside any window — the notebook guarantees this by trimming to the common calendar + forward-filling before calling.

### Component 2 — `notebooks/absorption_ratio.py` (new notebook)

Databricks notebook following `cache_refresh.py` conventions (`%pip install`, `sys.path.insert(0, "/Workspace/Users/sl.ilya1987@gmail.com/pytvtools-core/src")`, `dbutils.widgets`).

**Widgets:**

| widget | default | meaning |
|--------|---------|---------|
| `universe` | `SPDR_SECTORS` | watchlist key; resolved via `get_watchlist()` (code-based). |
| `n_eigenvectors` | `1` | int count or fraction (0.2). |
| `daily_window` | `500` | daily-target window in bars. |
| `weekly_window` | `52` | weekly-target window in bars. |
| `spx_symbol` | `SPCFD:SPX` | index plotted alongside AR. |
| `mode` | `view` | `view` = plot + save HTML; `backfill` = persist AR series to a UC table (stub for future research). |

**Flow:**
1. Resolve universe symbols (`get_watchlist("SPDR_SECTORS")`). On `KeyError`, print valid choices and abort.
2. Spark-load closes at `1D` and `1W` for the universe + `1D` candles for the SPX symbol from `workspace.chartdata.ohlcv`.
3. Pandas pivot `symbol→column` (column order = sorted symbols), index = timestamp.
   - **Trim to common calendar**: drop leading range where any asset is NaN (bounded by XLC→2018 for the full 11; a notebook comment notes the 9 originals extend to 1998).
   - Forward-fill residual gaps per column, then drop rows with any NaN; assert no-NaN before calling the rolling fn.
4. Call `rolling_absorption_ratio` twice — daily variant (`1D` closes, `daily_window`) and weekly variant (`1W` closes, `weekly_window`).
5. Build Lightweight Charts HTML with `Chart`:
   - Pane 0 (height ~420): SPX 1D candles.
   - Pane 1 (height ~190): daily AR line + weekly AR line, auto colors, time-scale synced (existing multi-pane sync).
   - `displayHTML(html)`; write `html` to `/Volumes/workspace/chartdata/chart_output/absorption_ratio_YYYY-MM-DD.html` (notebook executes `CREATE VOLUME IF NOT EXISTS workspace.chartdata.chart_output`).
6. `mode='backfill'`: write aligned `(timestamp, ar_daily, ar_weekly, spx_close)` rows to `workspace.chartdata.absorption_ratio` (schema created on demand), still printing the HTML.

## Testing (`tests/test_measures.py`, added to `CORE_TESTS`)

- `absorption_ratio` on a small fixed matrix vs a hand-computed expected value.
- Fraction (0.2) vs int (=1) `n_eigenvectors` — monotonicity sanity check (more eigenvectors → higher-or-equal AR).
- `rolling_absorption_ratio`: window length, alignment to end-of-window, `step`, NaN handling.
- Synthetic data: 2 assets where one perfectly tracks the other → AR ≈ 1.0 with 1 eigenvector.

Local test command: `python3 -m pytest tests/test_measures.py -q` (numpy required in the local venv).

## Error handling

- Universe resolution `KeyError` → clear message with valid keys, abort.
- Empty data after load → explicit error, never plot an empty chart.
- NaN in a covariance window → assertion error, message points at the trim/forward-fill step.
- Volume write failure → print HTML preview + warn, do not crash the cell.

## Deployment & sync

- Add `notebooks/absorption_ratio.py` to `CORE_NOTEBOOKS`; add `tests/test_measures.py` to `CORE_TESTS`; add `numpy` to synced `pyproject.toml` deps (generated by `sync_core.py`).
- `python scripts/sync_core.py ../pytvtools-core-public --commit "feat(core): absorption ratio + notebook"`
- `git -C ../pytvtools-core-public push`
- Force-sync the Databricks workspace git folder (`repo_id=2757908263996995`, branch `main`, `dangerously_force_discard_all=True`).
- Run the notebook via the on-demand job (`646435410260973`) or interactively to view the chart.

## Out of scope (POC)

No default AR persistence (backfill is a stub for a future research task). No universe-from-registry for arbitrary lists (code-based resolution already covers `SPDR_SECTORS`/`SP500`/`US_STOCKS`). No crash/event markers or threshold bands on the chart.