# Databricks notebook source
# MAGIC %md
# MAGIC # Absorption Ratio (Kritzman et al. 2010) + SPX
# MAGIC
# MAGIC Computes the absorption ratio of a configurable universe from
# MAGIC `workspace.chartdata.ohlcv` and plots it alongside the S&P 500 with
# MAGIC TradingView Lightweight Charts (two time-synced panes).
# MAGIC
# MAGIC | Widget | Default | Meaning |
# MAGIC |--------|---------|---------|
# MAGIC | `universe` | `SPDR_SECTORS` | watchlist key (code-resolved) |
# MAGIC | `n_eigenvectors` | `1` | int count, or 0.2 fraction |
# MAGIC | `daily_window` | `500` | daily variant rolling window (bars) |
# MAGIC | `weekly_window` | `52` | weekly variant rolling window (bars) |
# MAGIC | `spx_symbol` | `SPCFD:SPX` | index plotted on the top pane |
# MAGIC | `mode` | `view` | `view`=plot+save HTML, `backfill`=persist AR to UC table |

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

print(
    f"universe={universe} n_eigenvectors={n_eigenvectors} "
    f"daily_window={daily_window} weekly_window={weekly_window} "
    f"spx={spx_symbol} mode={mode}"
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
# MAGIC ## Compute absorption ratio (both variants)

# COMMAND ----------

from pytvtools_core.measures import rolling_absorption_ratio

ends_d, ar_daily = rolling_absorption_ratio(
    daily.to_numpy(float), window=daily_window, n_eigenvectors=n_eigenvectors
)
ends_w, ar_weekly = rolling_absorption_ratio(
    weekly.to_numpy(float), window=weekly_window, n_eigenvectors=n_eigenvectors
)

# window-end timestamps (unix seconds)
dates_d = daily.index[ends_d]
dates_w = weekly.index[ends_w]
print(f"Daily AR: {len(ar_daily)} pts, last={ar_daily[-1]:.4f}")
print(f"Weekly AR: {len(ar_weekly)} pts, last={ar_weekly[-1]:.4f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Build the Lightweight Charts HTML

# COMMAND ----------

# SPX candles for the top pane (trimmed to the aligned daily range).
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

# Chart.add_line aligns values POSITIONALLY to bar_times (the SPX candle
# timestamps). Map AR value-by-timestamp, then walk the SPX timeline emitting
# None where no window has completed yet.
ar_by_ts = {int(ts): float(v) for ts, v in zip(dates_d, ar_daily)}
ar_daily_aligned = [ar_by_ts.get(int(b["time"])) for b in spx_bars]

# Weekly ends fall on Fridays; forward-fill onto the SPX daily axis.
wk_by_ts = {int(ts): float(v) for ts, v in zip(dates_w, ar_weekly)}
ar_weekly_aligned: list[float | None] = [wk_by_ts.get(int(b["time"])) for b in spx_bars]
carry: float | None = None
for i, v in enumerate(ar_weekly_aligned):
    if v is not None:
        carry = v
    else:
        ar_weekly_aligned[i] = carry

# COMMAND ----------

from pytvtools_core.chart import Chart

chart = Chart(
    width=1200,
    main_height=420,
    title=f"Absorption Ratio — {universe}",
    ticker=f"AR (n={n_eigenvectors}) vs {spx_symbol}",
)
chart.set_candles(spx_bars, timeframe="1D")           # pane 0
chart.add_pane(height=190)                            # pane 1 (shares bar_times)
chart.add_line(ar_daily_aligned, name=f"AR daily ({daily_window}d)", pane=1)
chart.add_line(ar_weekly_aligned, name=f"AR weekly ({weekly_window}w)", pane=1)

html = chart.render()
displayHTML(html)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Persist outputs

# COMMAND ----------

# Save an HTML copy to a UC volume (create on demand).
spark.sql("CREATE VOLUME IF NOT EXISTS workspace.chartdata.chart_output")
html_path = f"/Volumes/workspace/chartdata/chart_output/absorption_ratio_{datetime.now(timezone.utc):%Y-%m-%d}.html"
try:
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Saved: {html_path}")
except Exception as exc:
    print(f"WARN: could not write HTML to volume ({exc}); preview shown above instead")

# COMMAND ----------

if mode == "backfill":
    import pandas as pd

    out = pd.DataFrame({
        "ts": daily.index[ends_d].astype("int64"),
        "ar_daily": ar_daily,
    })
    # Align weekly AR + SPX close to the daily axis via merge_asof.
    wk = pd.DataFrame({"ts": dates_w.astype("int64"), "ar_weekly": ar_weekly})
    spx = pd.DataFrame({"ts": [b["time"] for b in spx_bars],
                        "spx_close": [b["close"] for b in spx_bars]})
    out = pd.merge_asof(out, wk, on="ts", direction="backward")
    out = pd.merge_asof(out, spx, on="ts", direction="backward")
    out = out.rename(columns={"ts": "timestamp"})
    spark.createDataFrame(out).write.mode("overwrite") \
         .option("overwriteSchema", "true") \
         .saveAsTable("workspace.chartdata.absorption_ratio")
    print("Backfilled workspace.chartdata.absorption_ratio")