# Databricks notebook source
# MAGIC %md
# MAGIC # Market Caps Builder
# MAGIC
# MAGIC Refreshes `workspace.chartdata.market_caps` — one row per (symbol,
# MAGIC snapshot_date) holding the current market cap (`market_cap_basic`) of
# MAGIC every S&P 500 member, fetched from the TradingView scanner. Each run
# MAGIC appends a new dated snapshot; re-running on the same day replaces that
# MAGIC day's rows (idempotent). Consumers pick the latest snapshot:
# MAGIC `WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM ...)`.
# MAGIC
# MAGIC | Parameter | Value | Source |
# MAGIC |-----------|-------|--------|
# MAGIC | `table` | `workspace.chartdata.market_caps` | UC table |

# COMMAND ----------

# MAGIC %pip install -q websockets

# COMMAND ----------

import sys
from datetime import datetime, timezone

sys.path.insert(0, "/Workspace/Users/sl.ilya1987@gmail.com/pytvtools-core/src")

from pyspark.sql.types import StructType, StructField, StringType, DoubleType, DateType

from pytvtools_core.watchlists import get_sp500, get_market_caps
from pytvtools_core.cache import _CATALOG, _SCHEMA

OUTPUT_TABLE = f"{_CATALOG}.{_SCHEMA}.market_caps"
print(f"Refreshing {OUTPUT_TABLE}")

# COMMAND ----------

members = list(get_sp500().symbols)
# The scanner expects dot-form tickers (BRK.B). get_sp500() returns dash form
# (BRK-B) from the live Wikipedia fetch and underscore form (BRK_B) from the
# static fallback — normalize both.
tickers = [s.replace("-", ".").replace("_", ".") for s in members]
print(f"S&P 500 members: {len(tickers)}")

caps = get_market_caps(tickers)
print(f"Caps resolved: {len(caps)} / {len(tickers)}")

# COMMAND ----------

snapshot_date = datetime.now(timezone.utc).date()
rows = [
    {"symbol": sym, "market_cap": float(cap), "snapshot_date": snapshot_date}
    for sym, cap in caps.items()
]

df = spark.createDataFrame(rows, schema=StructType([
    StructField("symbol", StringType(), False),
    StructField("market_cap", DoubleType(), False),
    StructField("snapshot_date", DateType(), False),
]))

# Same-day re-run is idempotent: drop today's snapshot, then append.
# Guard the DELETE — the table may not exist on the first run.
from pyspark.sql.utils import AnalysisException
try:
    spark.sql(f"DELETE FROM {OUTPUT_TABLE} WHERE snapshot_date = DATE '{snapshot_date}'")
except AnalysisException:
    pass

df.write.mode("append").saveAsTable(OUTPUT_TABLE)
print(f"Wrote {len(rows)} rows for {snapshot_date}")

# COMMAND ----------

spark.sql(
    f"SELECT snapshot_date, count(*) AS n, round(sum(market_cap)/1e12, 2) AS total_trillion "
    f"FROM {OUTPUT_TABLE} GROUP BY snapshot_date ORDER BY snapshot_date DESC LIMIT 5"
).show(truncate=False)
