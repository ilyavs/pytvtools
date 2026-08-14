# Interactive Absorption Ratio Page — Design

## Goal

Upgrade the hosted absorption-ratio chart (https://ilyavs.github.io/pytvtools-core/demos/absorption_ratio.html)
into a **single self-contained interactive page** that lets the user switch between parameter
runs (`n = 1` and `n = 0.2`) with crosshair + time-scale sync, a fixed AR y-axis, resized
panes, no in-chart series titles, and a mobile-friendly layout. The `n = 0.2` run is computed
and its results persisted to UC, not scraped from HTML.

## References

- Kritzman, Li, Page & Rigobon (2011), *J. Portfolio Management* 37(4):112–126,
  doi:10.3905/jpm.2011.37.4.112, SSRN 1582687. `AR = Σ(top-N eigenvariances) / Σ(all eigenvariances)`.
- Existing pipeline: `notebooks/absorption_ratio.py` (view/backfill), core fn in
  `pytvtools_core/measures.py`, charts via `pytvtools_core/chart.Chart`.

## Decisions (from brainstorming)

| Question | Decision |
|----------|----------|
| DOD 1 data flow | Each parameter run **persists AR results to UC** (param-keyed); HTML generation reads data **per parameter from UC** — no HTML scraping |
| Render home | **Notebook renders the combined interactive page** (view mode becomes the combined generator; reproducible via job) |
| Persistence schema | **Single `param_key` table** `workspace.chartdata.absorption_ratio_runs` (easy to add params later) |
| Selector scope | `n_eigenvectors` only (`1` vs `2`, **integer counts**); everything else fixed (universe `SPDR_SECTORS_CORE`, daily 500 / weekly 52, SPX) |
| Selector behavior | Buttons above chart → `setData()` on the two AR lines; no reload |
| Crosshair sync | Position sync both ways via `setCrosshairPosition` / `clearCrosshairPosition` (same bar both panes) |
| AR y-axis | **Locked** — `autoscale:false`, min/max = global low/high across ALL AR lines of BOTH params, **+5% headroom**; SPX pane keeps autoscale |
| Pane heights | SPX 420→**360**, AR 190→**260** |
| Indicator labels | Drop in-chart series `title` labels; keep the right-side legend |
| Mobile | `.chart-wrap { max-width:100% }`; legend stacks below chart under ~980px via `@media` |
| Core changes | None to `chart.Chart`; the combined page is custom HTML emitted by the notebook |

## Architecture — data flow

### Stage 1 — per-parameter persistence (`mode=backfill`)

Notebook computes AR for the widget's `n_eigenvectors` (and windows) and writes
**parameter-tagged rows** to `workspace.chartdata.absorption_ratio_runs`:

| column | type | example |
|--------|------|---------|
| `param_key` | string | `n1_d500_w52` / `n2_d500_w52` |
| `n_eigenvectors` | double | 1.0 / 2.0 |
| `daily_window` | int | 500 |
| `weekly_window` | int | 52 |
| `universe` | string | `SPDR_SECTORS_CORE` |
| `timestamp` | bigint | unix sec |
| `ar_daily` | double | — |
| `ar_weekly` | double | — |

Each backfill run **overwrites only its own `param_key`** rows (delete-then-insert for that
key; other params untouched). Existing `workspace.chartdata.absorption_ratio` table stays
unchanged for the legacy backfill job chain.

Runs: `n=1` and `n=2` (both integer counts — with 9 assets, `n=0.2` would truncate
`0.2×9=1.8→1` and equal `n=1`, so `n=0.2` was dropped).

### Stage 2 — combined render (`mode=view`)

Notebook `view` mode now:
1. Loads SPX 1D candles from `ohlcv` (unchanged — not parameter-dependent).
2. Reads ALL rows from `absorption_ratio_runs`, pivots by `param_key` → per-param
   `ar_daily` / `ar_weekly` arrays aligned to the SPX daily timeline
   (daily exact-by-timestamp; weekly Friday ends forward-filled onto daily axis).
3. Computes the global AR min/max across all params' both lines (+5% headroom).
4. Emits the **combined interactive HTML** (below), `displayHTML`s it, and writes it to the
   UC volume as before.

## Page structure (custom HTML emitted by the notebook)

- **Selector bar** above the chart: two buttons `n = 1` / `n = 2`; active state highlighted;
  click → `setData(paramData)` on both AR line series; no reload.
- **Chart area** — Lightweight Charts, two panes: `chart0` SPX candles (360px, autoscale),
  `chart1` AR lines (260px, `priceScale().applyOptions({ autoscale:false, minValue, maxValue })`).
- **Right-side legend** — eye toggles + last value per series (reuse existing controls pattern);
  NO in-chart series `title`.
- **Sync** — existing time-scale sync (`setVisibleLogicalRange`) PLUS crosshair position sync
  (each pane's `subscribeCrosshairMove` forwards `{price, time}` to the other via
  `setCrosshairPosition`; on leave, `clearCrosshairPosition`).
- **Mobile** — `.chart-wrap { max-width:100% }`, `@media (max-width: 980px)` stacks the legend
  column under the chart full-width; script adds a container-width fit if needed.
- Data embedded as JS literals: `spxCandles`, `params: { n1: {arDaily, arWeekly}, n2: {...} }`.

## Notebook changes (`notebooks/absorption_ratio.py`)

- **Backfill**: replace single-table write with param-keyed upsert to
  `absorption_ratio_runs` (delete existing rows for `param_key`, insert new).
- **View**: read `absorption_ratio_runs`, pivot per `param_key`, build the combined page via
  a helper that emits the custom HTML/JS (kept in the notebook — no `chart.Chart` changes).
- Keep SPX candle loading, AR computation, `Chart`-free rendering for the combined mode.
- Widgets unchanged; `mode` semantics: `view` = combined render, `backfill` = param persistence.

## Verification

1. Backfill `n=1` and `n=2` (two job runs) → `absorption_ratio_runs` has 2 distinct
   `param_key` groups, sensible row counts, weekly ≤ daily rows.
2. View render → HTML contains: selector buttons, both params' data literals,
   `setCrosshairPosition`, `autoscale:false` with computed min/max, heights 360/260,
   media query, no series `title` in AR series options.
3. Download volume HTML → commit `demos/absorption_ratio.html` → push → Pages legacy
   auto-rebuilds → verify live URL HTTP 200 + data intact.
4. Open locally in a browser: switch n=1 ↔ n=2, drag crosshair across panes (positions
   track), confirm AR axis fixed (does not rescale when hiding a line), mobile viewport check.

## Out of scope

- No selector for windows/universe/SPX symbol (only `n_eigenvectors` per DOD).
- No `chart.Chart` API changes.
- No autoscale toggle for the AR pane (fixed per DOD).
