# Demo Notebook + HTML Product Sync — Design

## Goal

Give the two repos a single, documented sync path for the demo notebook and the
Pages-hosted HTML products, with a canonical copy of the demos living in the
`pytvtools` repo.

## Decisions (from brainstorming)

| Question | Decision |
|----------|----------|
| Scope | Document + use the existing sync script (`scripts/sync_core.py`) to include the demos — no new tooling |
| Canonical home | `pytvtools/demos/` is the single source of truth for demo HTML products and the AAPL generator |
| `apps/research` duplicates | `demo.py` + `demo_chart.html` deleted there (superseded by `demos/`); the Research App itself is untouched |
| Pages paths | `pages.yml` now copies `demos/demo_chart.html` → `_deploy/index.html` (pytvtools site unchanged behavior) |
| Core demos | Kept in core repo at `demos/`, but carried there by `sync_core.py` from pytvtools — never hand-edited there |

## Architecture — sync flow

### Notebook source sync (unchanged)

`pytvtools/notebooks/absorption_ratio.py` → `scripts/sync_core.py` → pytvtools-core
`notebooks/` → push → Databricks workspace git folder pulls it for jobs.

### HTML product sync (new)

1. `notebooks/absorption_ratio.py` run in **Databricks `view` mode** reads
   `workspace.chartdata.ohlcv` + `absorption_ratio_runs`, renders the combined page, and
   writes it to the UC volume `chart_output/`. This is the only step that needs Databricks.
2. Download the volume HTML → overwrite `pytvtools/demos/absorption_ratio.html`.
3. Run `sync_core.py` → the `CORE_DEMOS` block copies `demos/*` into core `demos/` → commit + push.
4. pytvtools-core Pages auto-rebuilds → `ilyavs.github.io/pytvtools-core/demos/absorption_ratio.html`.

### AAPL demo (unchanged behavior, new location)

`demos/demo.py` (moved from `apps/research/demo.py`, byte-identical) regenerates
`demos/demo_chart.html` over live WebSocket (no UC). `demos/demo_chart.html` feeds:
- pytvtools's own Pages site via `.github/workflows/pages.yml` → `_deploy/index.html`
- core's `demos/demo_chart.html` via `sync_core.py`

## File layout

```
pytvtools/
  demos/
    absorption_ratio.html   # canonical AR product (from UC volume, fixed layout+JS)
    demo_chart.html         # canonical AAPL demo
    demo.py                 # AAPL generator (from apps/research, moved)
  apps/research/
    app.py, applib/, templates/, app.yaml, databricks.yml, static/  # untouched
    [demo.py, demo_chart.html removed]
  scripts/sync_core.py      # + CORE_DEMOS block
  .github/workflows/pages.yml  # points at demos/demo_chart.html
  CLAUDE.md                 # "Demo HTML products" section
pytvtools-core-public/
  demos/                    # synced from pytvtools (never hand-edited)
  AGENTS.md, CLAUDE.md      # "synced content" notes
```

## Error handling

- `sync_core.py` preserves its per-file `if exists()` guard — missing demo files are
  skipped with no error; copied files are printed to the terminal.
- If the AR HTML is missing from `demos/`, sync still succeeds (misses only that file).

## Verification

1. `python scripts/sync_core.py ../pytvtools-core-public` (no `--commit`) — prints
   `Copied absorption_ratio.html`, `Copied demo_chart.html`, `Copied demo.py`; working
   trees of both repos show those as the only changes.
2. AR page renders in headless Chromium post-fix (applyParam seeding + flex-wrap) — no JS
   errors, both panes non-empty.
3. Both Pages URLs return HTTP 200 after push (manual/observational).

## Out of scope

- No new generation CLI; the AR HTML still requires a Databricks `view` run.
- Core package (`chart.Chart`, etc.) untouched.
- Databricks workspace git-folder force-sync unchanged (SDK `repos.update`).