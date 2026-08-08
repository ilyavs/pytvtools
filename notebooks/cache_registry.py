# Databricks notebook source
# MAGIC %md
# MAGIC # Symbol Registry Builder
# MAGIC
# MAGIC Builds/refreshes `workspace.chartdata.symbol_registry` — one row per
# MAGIC (symbol, watchlist) for all watchlists + S&P 500, with first_listed /
# MAGIC last_updated derived from `workspace.chartdata.ohlcv`.
# MAGIC
# MAGIC | Parameter | Value | Source |
# MAGIC |-----------|-------|--------|
# MAGIC | `table` | `workspace.chartdata.symbol_registry` | UC table |

# COMMAND ----------

# MAGIC %pip install -q websockets

# COMMAND ----------

import sys
sys.path.insert(0, "/Workspace/Users/sl.ilya1987@gmail.com/pytvtools-core/src")

import pyspark.sql.functions as F
from pyspark.sql.types import StructType, StructField, StringType, TimestampType

from pytvtools_core.watchlists import registry_rows
from pytvtools_core.cache import _CATALOG, _SCHEMA

OUTPUT_TABLE = f"{_CATALOG}.{_SCHEMA}.symbol_registry"
OHLCV_TABLE = f"{_CATALOG}.{_SCHEMA}.ohlcv"

print(f"Building registry {OUTPUT_TABLE} from {OHLCV_TABLE}")

# COMMAND ----------

# 1. build (symbol, watchlist, source) entries - all watchlists + S&P 500
entries = registry_rows()
print(f"Registry entries: {len(entries)}")

# COMMAND ----------

# 2. join to per-symbol first/last timestamp across ALL timeframes
df = spark.createDataFrame(entries, schema=StructType([
    StructField("symbol", StringType(), False),
    StructField("watchlist", StringType(), False),
    StructField("source", StringType(), False),
]))

agg = (
    spark.table(OHLCV_TABLE)
    .groupBy("symbol")
    .agg(
        F.min("timestamp").alias("first_listed"),
        F.max("timestamp").alias("last_updated"),
    )
)

out = df.join(agg, on="symbol", how="left")
out = out.select("symbol", "watchlist", "source", "first_listed", "last_updated")

# COMMAND ----------

# 3. full rebuild - idempotent
out.createOrReplaceTempView("_registry_v")
spark.sql(f"CREATE OR REPLACE TABLE {OUTPUT_TABLE} USING DELTA AS SELECT * FROM _registry_v")

# COMMAND ----------

# 4. summary
total = spark.table(OUTPUT_TABLE).count()
with_bars = out.filter(F.col("last_updated").isNotNull()).count()
print(f"Done. {OUTPUT_TABLE}: {total} rows, {with_bars} with data.")
print("Top watchlists:")
spark.sql(
    f"SELECT watchlist, count(*) AS n FROM {OUTPUT_TABLE} GROUP BY watchlist ORDER BY n DESC"
).show(truncate=False)
