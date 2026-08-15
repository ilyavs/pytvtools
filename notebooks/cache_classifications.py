# Databricks notebook source
# MAGIC %md
# MAGIC # Symbol Classifications Builder
# MAGIC
# MAGIC Builds/refreshes `workspace.chartdata.symbol_classifications` — one row per
# MAGIC (symbol, taxonomy) for the GICS (S&P 500 members, four-tier roll-up) and
# MAGIC TradingView (all US stocks, ICB-style) taxonomies.
# MAGIC
# MAGIC | Parameter | Value | Source |
# MAGIC |-----------|-------|--------|
# MAGIC | `table` | `workspace.chartdata.symbol_classifications` | UC table |

# COMMAND ----------

# MAGIC %pip install -q websockets

# COMMAND ----------

import sys
sys.path.insert(0, "/Workspace/Users/sl.ilya1987@gmail.com/pytvtools-core/src")

from pyspark.sql.types import (
    StructType, StructField, StringType, TimestampType,
)
from datetime import datetime

from pytvtools_core.classifications import classification_rows
from pytvtools_core.cache import _CATALOG, _SCHEMA

OUTPUT_TABLE = f"{_CATALOG}.{_SCHEMA}.symbol_classifications"
print(f"Building {OUTPUT_TABLE}")

# COMMAND ----------

rows = classification_rows()
print(f"Rows: {len(rows)} "
      f"({sum(1 for r in rows if r['taxonomy'] == 'gics')} gics, "
      f"{sum(1 for r in rows if r['taxonomy'] == 'tv')} tv)")

# COMMAND ----------

df = spark.createDataFrame(rows, schema=StructType([
    StructField("symbol", StringType(), False),
    StructField("taxonomy", StringType(), False),
    StructField("sector", StringType(), True),
    StructField("industry_group", StringType(), True),
    StructField("industry", StringType(), True),
    StructField("sub_industry", StringType(), True),
    StructField("security", StringType(), True),
    StructField("refreshed_at", TimestampType(), True),
])).select(
    "symbol", "taxonomy", "sector", "industry_group",
    "industry", "sub_industry", "security", "refreshed_at",
)

df.createOrReplaceTempView("_classifications_v")
spark.sql(f"CREATE OR REPLACE TABLE {OUTPUT_TABLE} USING DELTA AS SELECT * FROM _classifications_v")

# COMMAND ----------

print(f"Done. {OUTPUT_TABLE}: {spark.table(OUTPUT_TABLE).count()} rows.")
spark.sql(
    f"SELECT taxonomy, count(*) AS n, count(sector) AS with_sector "
    f"FROM {OUTPUT_TABLE} GROUP BY taxonomy ORDER BY taxonomy"
).show(truncate=False)
