# Databricks notebook source
# MAGIC %md
# MAGIC # Absorption Ratio (Kritzman et al. 2010) + SPX
# MAGIC
# MAGIC Computes the absorption ratio of a configurable universe from
# MAGIC `workspace.chartdata.ohlcv` and plots it alongside the S&P 500 with
# MAGIC TradingView Lightweight Charts (two time-synced panes).
# MAGIC
# MAGIC **Data flow.** Each parameter run (`n_eigenvectors`, windows) is persisted to
# MAGIC `workspace.chartdata.absorption_ratio_runs` (param-keyed). The interactive page is
# MAGIC then rendered from ALL stored parameter runs — the viewer can switch between them.
# MAGIC
# MAGIC | Widget | Default | Meaning |
# MAGIC |--------|---------|---------|
# MAGIC | `universe` | `SPDR_SECTORS` | watchlist key (code-resolved) |
# MAGIC | `n_eigenvectors` | `1` | int count, or 0.2 fraction |
# MAGIC | `daily_window` | `500` | daily variant rolling window (bars) |
# MAGIC | `weekly_window` | `52` | weekly variant rolling window (bars) |
# MAGIC | `spx_symbol` | `SPCFD:SPX` | index plotted on the top pane |
# MAGIC | `mode` | `view` | `backfill`=persist this run's AR to UC (param-keyed); `view`=render interactive page from all stored runs |

# COMMAND ----------

# MAGIC %md
# MAGIC ## Initialize

# COMMAND ----------

# MAGIC %pip install -q websockets

# COMMAND ----------

import sys
from datetime import datetime, timezone

sys.path.insert(0, "/Workspace/Users/sl.ilya1987@gmail.com/pytvtools-core/src")

dbutils.widgets.text("universe", "SPDR_SECTORS")
dbutils.widgets.text("n_eigenvectors", "1")
dbutils.widgets.text("daily_window", "500")
dbutils.widgets.text("weekly_window", "52")
dbutils.widgets.text("spx_symbol", "SPCFD:SPX")
dbutils.widgets.text("mode", "view")

universe = dbutils.widgets.get("universe")
n_eigenvectors_raw = dbutils.widgets.get("n_eigenvectors")
n_eigenvectors = (
    float(n_eigenvectors_raw) if "." in n_eigenvectors_raw else int(n_eigenvectors_raw)
)
daily_window = int(dbutils.widgets.get("daily_window"))
weekly_window = int(dbutils.widgets.get("weekly_window"))
spx_symbol = dbutils.widgets.get("spx_symbol")
mode = dbutils.widgets.get("mode")
assert mode in ("view", "backfill"), f"Invalid mode: {mode}"

param_key = f"n{n_eigenvectors}_d{daily_window}_w{weekly_window}"

print(
    f"universe={universe} n_eigenvectors={n_eigenvectors} "
    f"daily_window={daily_window} weekly_window={weekly_window} "
    f"spx={spx_symbol} mode={mode} param_key={param_key}"
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Resolve universe symbols

# COMMAND ----------

from pytvtools_core.watchlists import get_watchlist, get_sp500, get_us_stocks

_VALID_KEYS = (
    "SPDR_SECTORS, SPDR_INDUSTRIES, SPDR_ALL, CRYPTO, METALS_MINERS, "
    "INDEX_FUTURES, INDEX_CFDS, INDEX_ETFS, BONDS, OIL, URANIUM_STRATEGIC, "
    "SP500, US_STOCKS"
)

try:
    if universe == "SP500":
        symbols = sorted(get_sp500().symbols)
    elif universe == "US_STOCKS":
        symbols = sorted(get_us_stocks().symbols)
    else:
        wl = get_watchlist(universe)
        symbols = sorted(wl.symbols)
except Exception as exc:
    print(f"Unknown universe. Valid keys: {_VALID_KEYS}")
    raise exc

print(f"Universe {universe}: {len(symbols)} symbols")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load closes from UC cache

# COMMAND ----------

_OHLCV = "workspace.chartdata.ohlcv"


def load_closes(symbols: list[str], timeframe: str) -> "pandas.DataFrame":
    """Pivot close prices: index=unix-ts, columns=symbol."""
    import pandas as pd

    inlist = ", ".join(f"'{s}'" for s in symbols)
    rows = spark.sql(
        f"SELECT UNIX_TIMESTAMP(timestamp) AS ts, symbol, close "
        f"FROM {_OHLCV} WHERE timeframe = '{timeframe}' AND symbol IN ({inlist}) "
        f"ORDER BY ts"
    ).collect()
    records = [
        {"ts": int(r["ts"]), "symbol": r["symbol"], "close": float(r["close"])}
        for r in rows
    ]
    if not records:
        raise RuntimeError(f"No data for timeframe={timeframe}")
    df = pd.DataFrame(records).pivot(index="ts", columns="symbol", values="close")
    df.columns = [str(c) for c in df.columns]
    return df.sort_index()


closes_1d = load_closes(symbols, "1D")
closes_1w = load_closes(symbols, "1W")
print(f"1D closes: {closes_1d.shape} ({closes_1d.index.min()}..{closes_1d.index.max()})")
print(f"1W closes: {closes_1w.shape} ({closes_1w.index.min()}..{closes_1w.index.max()})")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Align to common calendar

# COMMAND ----------

# Trim leading range where any asset is NaN (bounded by the youngest listing),
# forward-fill residual listing gaps, then require fully-populated rows.
def align_common(df: "pandas.DataFrame") -> "pandas.DataFrame":
    df = df[df.notna().all(axis=1)]  # leading-trim: drop rows missing ANY asset
    df = df.ffill()                  # close internal listing gaps
    df = df.dropna(how="any")        # drop any remaining incomplete rows
    return df


daily = align_common(closes_1d)
weekly = align_common(closes_1w)
print(f"Aligned 1D: {daily.shape} ({daily.index.min()}..{daily.index.max()})")
print(f"Aligned 1W: {weekly.shape} ({weekly.index.min()}..{weekly.index.max()})")

if daily.shape[0] < daily_window + 1:
    raise RuntimeError("Insufficient aligned daily bars for the requested window")
if weekly.shape[0] < weekly_window + 1:
    raise RuntimeError("Insufficient aligned weekly bars for the requested window")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load SPX candles (shared by backfill + view)

# COMMAND ----------

rows = spark.sql(
    f"SELECT UNIX_TIMESTAMP(timestamp) AS ts, open, high, low, close "
    f"FROM {_OHLCV} WHERE symbol = '{spx_symbol}' AND timeframe = '1D' ORDER BY ts"
).collect()
spx_bars = []
for r in rows:
    if daily.index.min() <= r["ts"] <= daily.index.max():
        spx_bars.append({
            "time": int(r["ts"]),
            "open": float(r["open"]), "high": float(r["high"]),
            "low": float(r["low"]), "close": float(r["close"]),
        })
print(f"SPX candles: {len(spx_bars)}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Compute absorption ratio (both variants) — backfill only

# COMMAND ----------

if mode == "backfill":
    from pytvtools_core.measures import rolling_absorption_ratio

    ends_d, ar_daily = rolling_absorption_ratio(
        daily.to_numpy(float), window=daily_window, n_eigenvectors=n_eigenvectors,
        half_life=daily_window / 2,
    )
    ends_w, ar_weekly = rolling_absorption_ratio(
        weekly.to_numpy(float), window=weekly_window, n_eigenvectors=n_eigenvectors,
        half_life=weekly_window / 2,
    )

    # window-end timestamps (unix seconds)
    dates_d = daily.index[ends_d]
    dates_w = weekly.index[ends_w]
    print(f"Daily AR: {len(ar_daily)} pts, last={ar_daily[-1]:.4f}")
    print(f"Weekly AR: {len(ar_weekly)} pts, last={ar_weekly[-1]:.4f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Persist this run to UC (backfill)

# COMMAND ----------

if mode == "backfill":
    import pandas as pd
    from pyspark.sql.utils import AnalysisException

    out = pd.DataFrame({
        "param_key": param_key,
        "n_eigenvectors": float(n_eigenvectors),
        "daily_window": daily_window,
        "weekly_window": weekly_window,
        "universe": universe,
        "timestamp": daily.index[ends_d].astype("int64"),
        "ar_daily": ar_daily,
    })
    # Align weekly AR onto the daily axis via merge_asof (backward).
    wk = pd.DataFrame({"timestamp": dates_w.astype("int64"), "ar_weekly": ar_weekly})
    out = pd.merge_asof(out, wk, on="timestamp", direction="backward")

    # Overwrite this param_key's rows only (leave other params untouched).
    try:
        spark.sql(
            f"DELETE FROM workspace.chartdata.absorption_ratio_runs "
            f"WHERE param_key = '{param_key}'"
        )
    except AnalysisException:
        pass  # first run — table does not exist yet
    spark.createDataFrame(out).write.mode("append") \
         .option("mergeSchema", "true") \
         .saveAsTable("workspace.chartdata.absorption_ratio_runs")
    print(f"Persisted {param_key} → workspace.chartdata.absorption_ratio_runs ({len(out)} rows)")

    spark.sql("SELECT param_key, COUNT(*) AS n FROM workspace.chartdata.absorption_ratio_runs GROUP BY param_key ORDER BY param_key").show(10, truncate=False)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Render the combined interactive page (view)

# COMMAND ----------

if mode == "view":
    import json

    # ── read all parameter runs from UC ─────────────────────────────
    rows = spark.sql(
        "SELECT param_key, n_eigenvectors, daily_window, weekly_window, "
        "       timestamp, ar_daily, ar_weekly "
        "FROM workspace.chartdata.absorption_ratio_runs ORDER BY timestamp"
    ).collect()
    if not rows:
        raise RuntimeError("absorption_ratio_runs is empty — run backfill first")

    from collections import OrderedDict

    runs: "OrderedDict[str, dict]" = OrderedDict()
    for r in rows:
        key = r["param_key"]
        runs.setdefault(key, {"param_key": key, "n_eigenvectors": float(r["n_eigenvectors"]),
                              "daily_window": int(r["daily_window"]),
                              "weekly_window": int(r["weekly_window"]),
                              "ar_daily": {}, "ar_weekly": {}})
        ts = int(r["timestamp"])
        runs[key]["ar_daily"][ts] = float(r["ar_daily"])
        if r["ar_weekly"] is not None:
            runs[key]["ar_weekly"][ts] = float(r["ar_weekly"])

    print(f"Stored parameter runs: {list(runs.keys())}")

    # ── align each run to the SPX daily timeline ─────────────────────
    def align_series(spx_times: list[int], by_ts: dict, forward_fill: bool) -> list[dict]:
        out: list[dict] = []
        carry = None
        for t in spx_times:
            v = by_ts.get(t)
            if forward_fill:
                if v is not None:
                    carry = v
                v = carry
            out.append({"time": t} if v is None else {"time": t, "value": round(v, 6)})
        return out

    spx_times = [b["time"] for b in spx_bars]
    # order: n=1 first (default), then others by n ascending
    ordered = sorted(runs.values(), key=lambda p: (p["n_eigenvectors"] != 1.0, p["n_eigenvectors"]))
    params = []
    for p in ordered:
        params.append({
            "key": p["param_key"],
            "label": f"n = {p['n_eigenvectors']:g}",
            "arDaily": align_series(spx_times, p["ar_daily"], forward_fill=False),
            "arWeekly": align_series(spx_times, p["ar_weekly"], forward_fill=True),
        })

    # ── AR axis is FIXED 0–1 (AR is a ratio of eigenvalues) ─────────
    # ── per-param AR all-time low per series (horizontal lines) ─────
    def _atl(series: str) -> dict:
        return {
            p["key"]: min(
                (d["value"] for d in p[series] if "value" in d),
                default=None,
            )
            for p in params
        }

    atl_daily_by_key = _atl("arDaily")
    atl_weekly_by_key = _atl("arWeekly")

    # ── last values (for legend, default = n=1) ─────────────────────
    def last_non_none(line: list[dict]):
        for d in reversed(line):
            if "value" in d:
                return d["value"]
        return None

    def num_or_null(v):
        return "null" if v is None else repr(float(v))

    default_key = params[0]["key"]
    def_p = params[0]
    spx_last = round(spx_bars[-1]["close"], 2) if spx_bars else 0.0

    # ── notes box text ───────────────────────────────────────────────
    t0 = datetime.fromtimestamp(spx_times[0], tz=timezone.utc).strftime("%Y-%m-%d")
    t1 = datetime.fromtimestamp(spx_times[-1], tz=timezone.utc).strftime("%Y-%m-%d")
    param_labels = " / ".join(p["label"] for p in params)

    # ═══════════════════════ HTML TEMPLATE ═══════════════════════════
    TPL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Absorption Ratio — {universe}</title>
<script src="https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #11171C; font-family: -apple-system, sans-serif; display: flex; flex-wrap: wrap; justify-content: center; }}
  .chart-wrap {{ width: 1200px; max-width: 100%; display: flex; flex-direction: row; flex-wrap: wrap; }}
  .chart-ticker {{ color: #E8ECF0; padding: 12px 0 4px; font-size: 15px; font-weight: 600; width: 100%; }}
  .selector {{ width: 100%; display: flex; align-items: center; gap: 8px; padding: 6px 0 10px; }}
  .selector-label {{ color: #C7D0DA; font-size: 13px; }}
  .selector button {{
    background: #1A2330; color: #C7D0DA; border: 1px solid #2A3440;
    border-radius: 6px; padding: 6px 16px; font-size: 13px; cursor: pointer; font-family: inherit;
  }}
  .selector button.active {{ background: hsl(137.5, 65%, 55%); color: #11171C; border-color: hsl(137.5, 65%, 55%); font-weight: 600; }}
</style>
</head>
<body>
<div class="chart-ticker">AR ({param_labels}) vs {spx_symbol}</div>
<div class="selector">
  <span class="selector-label">Parameters:</span>
  {selector_buttons}
</div>
<div class="chart-wrap">
<div class="chart-panes">
     <div id="chart0" style="width:100%;height:360px"></div>
     <div id="chart1" style="width:100%;height:200px"></div>
     <div id="chart2" style="width:100%;height:200px"></div>
   </div>
   <div class="chart-legends">
     <div id="l0" class="tv-legend" data-pane="0" style="height:360px;">
       <div class="tv-legend-row" data-series="cs0">
         <span class="tv-legend-eye" data-visible="1">&#128065;</span>
         <span class="tv-legend-swatch" style="background:#26a69a"></span>
         <span class="tv-legend-name">{spx_symbol}</span>
         <span class="tv-legend-value">{spx_last:.2f}</span>
       </div>
     </div>
     <div id="l1" class="tv-legend" data-pane="1" style="height:200px;">
       <div class="tv-legend-row" data-series="s1_0">
         <span class="tv-legend-eye" data-visible="1">&#128065;</span>
         <span class="tv-legend-swatch" style="background:hsl(0.0, 65%, 55%)"></span>
         <span class="tv-legend-name">AR daily ({daily_window}d)</span>
         <span class="tv-legend-value">{ar_daily_last_legend}</span>
       </div>
     </div>
     <div id="l2" class="tv-legend" data-pane="2" style="height:200px;">
       <div class="tv-legend-row" data-series="s1_1">
         <span class="tv-legend-eye" data-visible="1">&#128065;</span>
         <span class="tv-legend-swatch" style="background:hsl(137.5, 65%, 55%)"></span>
         <span class="tv-legend-name">AR weekly ({weekly_window}w)</span>
         <span class="tv-legend-value">{ar_weekly_last_legend}</span>
       </div>
     </div>
   </div>
</div>
<div class="chart-notes">
  <h3>About this chart</h3>
  <p>
    The <strong>absorption ratio (AR)</strong> measures the fraction of the total variance of a set
    of asset returns that is explained, or &ldquo;absorbed&rdquo;, by a fixed number of eigenvectors
    of the return covariance matrix. A high value implies the market is tightly coupled
    (&ldquo;compact&rdquo;) and therefore fragile: shocks propagate more quickly and broadly than
    when markets are loosely linked.
  </p>
  <p><strong>Calculation.</strong> Universe: the nine original SPDR Select Sector ETFs
  (XLK, XLY, XLP, XLE, XLF, XLV, XLI, XLB, XLU; the 1998-listed sectors, excluding the later
  XLC and XLRE). Daily and weekly returns are aligned to a common calendar
  (<span>{t0}</span>&rarr;<span>{t1}</span>). For each window we compute the
  eigen-decomposition of the return covariance matrix, estimated with exponential
  weighting whose half-life equals half the window (matching Kritzman, Li, Page &amp;
  Rigobon 2011), and set
  AR&nbsp;=&nbsp;&Sigma;<sub>i=1&nbsp;&hellip;&nbsp;k</sub>&nbsp;&lambda;<sub>i</sub>&nbsp;/&nbsp;&Sigma;<sub>i</sub>&nbsp;&lambda;<sub>i</sub>.
  The parameter selector above switches between retaining the top
  k&nbsp;=&nbsp;1 eigenvector (<span>n=1</span>) and the top
  k&nbsp;=&nbsp;2 eigenvectors (<span>n=2</span>). The daily
  series uses a rolling 500-bar window; the weekly series uses a rolling 52-bar window. AR is
  plotted beneath S&amp;P&nbsp;500 candles ({spx_symbol}) on a shared time axis, in two
  separate panes (daily and weekly) that share crosshairs; the AR axis is fixed to the full range
  across both parameter settings, and each pane shows its own all-time-low (ATL) line.
  </p>
  <p><strong>Reference.</strong>
  Mark Kritzman, Yuanzhen Li, S&eacute;bastien Page, and Roberto Rigobon,
  &ldquo;Principal Components as a Measure of Systemic Risk,&rdquo;
  <em>The Journal of Portfolio Management</em>, Summer 2011, 37(4):112&ndash;126,
  doi:10.3905/jpm.2011.37.4.112.
  The working paper (April 2010) is available on SSRN (No.&nbsp;1582687).
  </p>
  <blockquote>
    &ldquo;Compact markets do not always lead to asset depreciation, but most significant stock
    market drawdowns have been preceded by spikes in the absorption ratio. This suggests that spikes
    in the absorption ratio are a near necessary, but not sufficient, condition for market
    crashes.&rdquo; &mdash; Kritzman, Li, Page &amp; Rigobon (2011), p.&nbsp;123
  </blockquote>
  <p class="chart-notes-foot">Not investment advice. For research and education only.</p>
</div>
<style>
.chart-panes {{ flex: 1; min-width: 0; }}
.chart-legends {{ width: 220px; display: flex; flex-direction: column; padding-left: 8px; }}
.tv-legend {{
  background: rgba(17, 23, 28, 0.9); border: 1px solid #2A3440; border-radius: 6px;
  padding: 8px 12px; font-family: -apple-system, monospace; font-size: 12px;
  color: #E8ECF0; min-width: 180px; overflow-y: auto; margin-bottom: 4px;
}}
.tv-legend:last-child {{ margin-bottom: 0; }}
.tv-legend-row {{ display: flex; align-items: center; gap: 6px; padding: 2px 0; cursor: default; }}
.tv-legend-row.hidden {{ opacity: 0.4; text-decoration: line-through; }}
.tv-legend-eye {{ cursor: pointer; user-select: none; }}
.tv-legend-swatch {{ display: inline-block; width: 10px; height: 10px; border-radius: 2px; cursor: pointer; }}
.tv-legend-name {{ flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.tv-legend-value {{ text-align: right; color: #758696; font-variant-numeric: tabular-nums; }}
.chart-notes {{
  width: 1200px; max-width: 100%; flex-basis: 100%; margin: 14px 0 0; padding: 14px 18px;
  background: rgba(17, 23, 28, 0.9); border: 1px solid #2A3440; border-radius: 6px;
  color: #C7D0DA; font-family: -apple-system, sans-serif; font-size: 13px; line-height: 1.55;
}}
.chart-notes h3 {{ color: #E8ECF0; font-size: 14px; margin-bottom: 8px; }}
.chart-notes p {{ margin: 0 0 8px; }}
.chart-notes .chart-notes-foot {{ color: #758696; font-size: 11px; margin-bottom: 0; }}
.chart-notes blockquote {{
  margin: 10px 0 10px 2px; padding: 8px 12px; border-left: 3px solid hsl(137.5, 65%, 55%);
  background: rgba(255, 255, 255, 0.03); color: #E8ECF0; font-style: italic;
}}
@media (max-width: 980px) {{
  .chart-panes {{ flex: 1 1 100%; }}
  .chart-legends {{ width: 100%; flex-direction: row; padding-left: 0; padding-top: 8px; }}
  .tv-legend {{ flex: 1; min-width: 0; }}
  .selector {{ flex-wrap: wrap; }}
}}
</style>
<script>
(function() {{
  var SPX = {spx_json};
  var PARAMS = {params_json};
  var ATL_DAILY = {atl_daily_json};
  var ATL_WEEKLY = {atl_weekly_json};
  var DEFAULT_KEY = {default_key_json};

  var chart0 = window.chart0 = LightweightCharts.createChart(
    document.getElementById("chart0"),
    {{"height": 360, "layout": {{"textColor": "#E8ECF0", "background": {{"type": "solid", "color": "#11171C"}}}}, "grid": {{"vertLines": {{"color": "#2A3440"}}, "horzLines": {{"color": "#2A3440"}}}}, "crosshair": {{"mode": 0}}, "rightPriceScale": {{"mode": 1, "borderColor": "#2A3440"}}, "timeScale": {{"timeVisible": true, "secondsVisible": false, "borderColor": "#2A3440"}}}}
  );
  window.cs0 = chart0.addSeries(LightweightCharts.CandlestickSeries, {{"upColor": "#26a69a", "downColor": "#ef5350", "borderUpColor": "#26a69a", "borderDownColor": "#ef5350", "wickUpColor": "#26a69a", "wickDownColor": "#ef5350"}});
  cs0.setData(SPX);

  var chart1 = window.chart1 = LightweightCharts.createChart(
    document.getElementById("chart1"),
    {{"height": 200, "layout": {{"textColor": "#E8ECF0", "background": {{"type": "solid", "color": "#11171C"}}}}, "grid": {{"vertLines": {{"color": "#2A3440"}}, "horzLines": {{"color": "#2A3440"}}}}, "crosshair": {{"mode": 0}}, "rightPriceScale": {{"borderColor": "#2A3440"}}, "timeScale": {{"timeVisible": true, "secondsVisible": false, "borderColor": "#2A3440"}}}}
  );
  window.s1_0 = chart1.addSeries(LightweightCharts.LineSeries, {{"lineWidth": 2, "color": "hsl(0.0, 65%, 55%)", "lastValueVisible": false, "priceLineVisible": false}});
  chart1.priceScale("right").applyOptions({{ autoScale: false, minValue: 0, maxValue: 1 }});

  var chart2 = window.chart2 = LightweightCharts.createChart(
    document.getElementById("chart2"),
    {{"height": 200, "layout": {{"textColor": "#E8ECF0", "background": {{"type": "solid", "color": "#11171C"}}}}, "grid": {{"vertLines": {{"color": "#2A3440"}}, "horzLines": {{"color": "#2A3440"}}}}, "crosshair": {{"mode": 0}}, "rightPriceScale": {{"borderColor": "#2A3440"}}, "timeScale": {{"timeVisible": true, "secondsVisible": false, "borderColor": "#2A3440"}}}}
  );
  window.s1_1 = chart2.addSeries(LightweightCharts.LineSeries, {{"lineWidth": 2, "color": "hsl(137.5, 65%, 55%)", "lastValueVisible": false, "priceLineVisible": false}});
  chart2.priceScale("right").applyOptions({{ autoScale: false, minValue: 0, maxValue: 1 }});

  // ── per-pane AR all-time-low price lines (update per param) ──
  var atlLineDaily = s1_0.createPriceLine({{ price: ATL_DAILY[DEFAULT_KEY] ?? 0, color: "#E91E63", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "ATL" }});
  var atlLineWeekly = s1_1.createPriceLine({{ price: ATL_WEEKLY[DEFAULT_KEY] ?? 0, color: "#E91E63", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "ATL" }});
  function updateAtlLine(line, key, map) {{
    var p = map[key];
    if (p === undefined || p === null) line.applyOptions({{ visible: false }});
    else line.applyOptions({{ price: p, visible: true }});
  }}

  // ── time-scale sync ──
  var charts = [chart0, chart1, chart2];
  var syncing = false;
  function sync(range) {{
    if (syncing) return;
    syncing = true;
    for (var i = 0; i < charts.length; i++) charts[i].timeScale().setVisibleLogicalRange(range);
    syncing = false;
  }}
  for (var i = 0; i < charts.length; i++) charts[i].timeScale().subscribeVisibleLogicalRangeChange(sync);

  // ── legend state + controls ──
  var ctx = window.__chartCtx = {{}};
  ctx._chartPanes = {{}};
  function lastVal(data) {{
    for (var i = data.length - 1; i >= 0; i--) if (data[i] && data[i].value !== undefined) return data[i].value;
    return undefined;
  }}
  ctx['cs0']  = {{ visible: true, series: cs0,  colorKey: 'upColor', color: '#26a69a',          _lastVal: {spx_last} }};
  ctx['s1_0'] = {{ visible: true, series: s1_0, colorKey: 'color',   color: 'hsl(0.0, 65%, 55%)',   _lastVal: {ar_daily_last_js} }};
  ctx['s1_1'] = {{ visible: true, series: s1_1, colorKey: 'color',   color: 'hsl(137.5, 65%, 55%)', _lastVal: {ar_weekly_last_js} }};
  ctx._chartPanes[0] = ["cs0"];
  ctx._chartPanes[1] = ["s1_0"];
  ctx._chartPanes[2] = ["s1_1"];

  function setupLegend(paneIdx) {{
    var leg = document.getElementById('l' + paneIdx);
    if (!leg) return;
    leg.addEventListener('click', function(e) {{
      var eye = e.target.closest('.tv-legend-eye');
      if (eye) {{
        var row = eye.closest('.tv-legend-row');
        var sid = row.dataset.series;
        var entry = ctx[sid];
        if (entry) {{
          entry.visible = !entry.visible;
          entry.series.applyOptions({{ visible: entry.visible }});
          row.classList.toggle('hidden', !entry.visible);
        }}
        return;
      }}
      var swatch = e.target.closest('.tv-legend-swatch');
      if (swatch) {{
        var row = swatch.closest('.tv-legend-row');
        var sid = row.dataset.series;
        var entry = ctx[sid];
        if (!entry) return;
        var picker = document.createElement('input');
        picker.type = 'color';
        picker.value = entry.color;
        picker.addEventListener('input', function() {{
          var c = picker.value;
          swatch.style.background = c;
          entry.color = c;
          var opts = {{}};
          if (entry.baseline) {{ opts.topLineColor = c; opts.bottomLineColor = c; }}
          else opts[entry.colorKey] = c;
          entry.series.applyOptions(opts);
        }});
        picker.addEventListener('blur', function() {{
          if (picker.parentNode) picker.parentNode.removeChild(picker);
        }});
        document.body.appendChild(picker);
        picker.click();
      }}
    }});
  }}
  setupLegend(0);
  setupLegend(1);
  setupLegend(2);

  // ── value maps for crosshair-position sync ──
  var spxCloseByTime = {{}};
  SPX.forEach(function(b) {{ spxCloseByTime[b.time] = b.close; }});
  var arDailyValByTime = {{}};
  var arWeeklyValByTime = {{}};
  function rebuildArMap(key) {{
    for (var k in arDailyValByTime) delete arDailyValByTime[k];
    for (var k in arWeeklyValByTime) delete arWeeklyValByTime[k];
    PARAMS[key].arDaily.forEach(function(p) {{ if (p.value !== undefined) arDailyValByTime[p.time] = p.value; }});
    PARAMS[key].arWeekly.forEach(function(p) {{ if (p.value !== undefined) arWeeklyValByTime[p.time] = p.value; }});
  }}

  // ── parameter selector ──
  var curKey = DEFAULT_KEY;
  function applyParam(key) {{
    curKey = key;
    s1_0.setData(PARAMS[key].arDaily);
    s1_1.setData(PARAMS[key].arWeekly);
    updateAtlLine(atlLineDaily, key, ATL_DAILY);
    updateAtlLine(atlLineWeekly, key, ATL_WEEKLY);
    ctx['s1_0']._lastVal = lastVal(PARAMS[key].arDaily);
    ctx['s1_1']._lastVal = lastVal(PARAMS[key].arWeekly);
    rebuildArMap(key);
    [[1, 's1_0', ctx['s1_0']._lastVal], [2, 's1_1', ctx['s1_1']._lastVal]].forEach(function(pair) {{
      var leg = document.getElementById('l' + pair[0]);
      var el = leg.querySelector('[data-series="' + pair[1] + '"] .tv-legend-value');
      if (el) el.textContent = (pair[2] !== undefined && pair[2] !== null) ? pair[2].toFixed(2) : '';
    }});
    document.querySelectorAll('.selector button').forEach(function(b) {{ b.classList.toggle('active', b.dataset.param === key); }});
  }}
  document.querySelectorAll('.selector button').forEach(function(b) {{
    b.addEventListener('click', function() {{ applyParam(b.dataset.param); }});
  }});
  applyParam(DEFAULT_KEY);

  // ── crosshair value tracking in legends (per pane) ──
  function trackLegend(chIdx) {{
    var chart = window["chart" + chIdx];
    if (!chart) return;
    chart.subscribeCrosshairMove(function(param) {{
      var ids = ctx._chartPanes[chIdx];
      var leg = document.getElementById("l" + chIdx);
      if (!ids || !leg) return;
      var isLeaving = !param.point || !param.time;
      ids.forEach(function(sid) {{
        var entry = ctx[sid];
        if (!entry || entry.series === undefined) return;
        var row = leg.querySelector('[data-series="' + sid + '"]');
        if (!row) return;
        var valEl = row.querySelector(".tv-legend-value");
        if (!valEl) return;
        if (isLeaving) {{
          if (entry._lastVal !== undefined && entry._lastVal !== null) valEl.textContent = entry._lastVal.toFixed(2);
          else valEl.textContent = "";
          return;
        }}
        var data = param.seriesData.get(entry.series);
        if (data) {{
          var v = data.value !== undefined ? data.value : data.close;
          if (v !== undefined) valEl.textContent = v.toFixed(2);
        }}
      }});
    }});
  }}
  trackLegend(0);
  trackLegend(1);
  trackLegend(2);

  // ── crosshair position sync (both directions, guarded) ──
  var _xGuard = false;
  function link(src, dst, map) {{
    src.subscribeCrosshairMove(function(param) {{
      if (_xGuard) return;
      _xGuard = true;
      try {{
        if (!param.time || !param.point) {{ dst.clearCrosshairPosition(); }}
        else {{
          var p = map[param.time];
          if (p !== undefined) dst.setCrosshairPosition(p, param.time);
        }}
      }} finally {{ _xGuard = false; }}
    }});
  }}
  link(chart0, chart1, arDailyValByTime);
  link(chart0, chart2, arWeeklyValByTime);
  link(chart1, chart0, spxCloseByTime);
  link(chart2, chart0, spxCloseByTime);
}})();
</script>
</body>
</html>
"""

    # ── selector buttons ─────────────────────────────────────────────
    buttons = []
    for p in params:
        active = " active" if p["key"] == default_key else ""
        buttons.append(
            f'<button id="btn-{p["key"]}" class="param-btn{active}" '
            f'data-param="{p["key"]}">{p["label"]}</button>'
        )
    selector_buttons = "".join(buttons)

    ar_daily_last = num_or_null(last_non_none(def_p["arDaily"]))
    ar_weekly_last = num_or_null(last_non_none(def_p["arWeekly"]))

    def fmt2(v_or_null: str) -> str:
        if v_or_null == "null":
            return ""
        return f"{float(v_or_null):.2f}"

    html = TPL.format(
        universe=universe,
        spx_symbol=spx_symbol,
        param_labels=param_labels,
        selector_buttons=selector_buttons,
        spx_json=json.dumps(spx_bars, separators=(",", ":")),
        params_json=json.dumps(
            {p["key"]: {"arDaily": p["arDaily"], "arWeekly": p["arWeekly"]} for p in params},
            separators=(",", ":"),
        ),
        default_key_json=json.dumps(default_key),
        atl_daily_json=json.dumps(atl_daily_by_key, separators=(",", ":")),
        atl_weekly_json=json.dumps(atl_weekly_by_key, separators=(",", ":")),
        spx_last=spx_last,
        ar_daily_last_js=ar_daily_last,
        ar_weekly_last_js=ar_weekly_last,
        ar_daily_last_legend=fmt2(ar_daily_last),
        ar_weekly_last_legend=fmt2(ar_weekly_last),
        daily_window=daily_window,
        weekly_window=weekly_window,
        t0=t0,
        t1=t1,
    )

    displayHTML(html)

    # ── save a copy to a UC volume ───────────────────────────────────
    spark.sql("CREATE VOLUME IF NOT EXISTS workspace.chartdata.chart_output")
    html_path = f"/Volumes/workspace/chartdata/chart_output/absorption_ratio_{datetime.now(timezone.utc):%Y-%m-%d}.html"
    try:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Saved: {html_path}")
    except Exception as exc:
        print(f"WARN: could not write HTML to volume ({exc}); preview shown above instead")
