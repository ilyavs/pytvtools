# Databricks notebook source
# MAGIC %md
# MAGIC # Market Data Cache Refresh
# MAGIC
# MAGIC Refreshes the UC market data cache for any predefined watchlist or a single symbol.
# MAGIC Run as a scheduled Databricks job or on-demand for ad-hoc refresh.
# MAGIC
# MAGIC | Parameter | Value | Source |
# MAGIC |-----------|-------|--------|
# MAGIC | `timeframe` | `"1D"`, `"1W"`, or `"1M"` | Job parameter |
# MAGIC | `watchlist` | `"SP500"`, `"METALS_MINERS"`, `"CRYPTO"`, etc. | Omit for single-symbol mode |
# MAGIC | `symbol` | `"NASDAQ:AAPL"` (optional) | Omit for watchlist batch |
# MAGIC | `mode` | `"incremental"` or `"backfill"` | Use ``backfill`` for initial load (pagination), ``incremental`` for scheduled runs |
# MAGIC | `table` | `workspace.chartdata.ohlcv` | UC table |
# MAGIC
# MAGIC **Available watchlists**: SPDR_SECTORS, SPDR_INDUSTRIES, SPDR_ALL, CRYPTO,
# MAGIC METALS_MINERS, INDEX_FUTURES, INDEX_CFDS, INDEX_ETFS, BONDS, OIL,
# MAGIC URANIUM_STRATEGIC.  Pass `"SP500"` for S&P 500 (fetched live from Wikipedia).

# COMMAND ----------

# MAGIC %pip install -q websockets

# COMMAND ----------

import sys
sys.path.insert(0, "/Workspace/Users/sl.ilya1987@gmail.com/pytvtools-core/src")

import asyncio
from pytvtools_core.cache import MarketDataCache

dbutils.widgets.text("timeframe", "1D")
dbutils.widgets.text("watchlist", "")
dbutils.widgets.text("symbol", "")
dbutils.widgets.text("mode", "incremental")

timeframe = dbutils.widgets.get("timeframe")
assert timeframe in ("1D", "1W", "1M"), f"Invalid timeframe: {timeframe}"

watchlist = dbutils.widgets.get("watchlist") or None
symbol = dbutils.widgets.get("symbol") or None
mode = dbutils.widgets.get("mode")
assert mode in ("incremental", "backfill"), f"Invalid mode: {mode}"

# COMMAND ----------

if symbol:
    symbols = [symbol]
    label = f"single={symbol}"
elif watchlist:
    if watchlist == "SP500":
        from pytvtools_core.watchlists import get_sp500
        wl = get_sp500()
    else:
        from pytvtools_core.watchlists import get_watchlist
        wl = get_watchlist(watchlist)
    symbols = sorted(wl.symbols)
    label = f"watchlist={watchlist} ({len(symbols)} symbols)"
else:
    # Default: S&P 500
    from pytvtools_core.watchlists import get_sp500
    wl = get_sp500()
    symbols = sorted(wl.symbols)
    label = f"S&P 500 batch ({len(symbols)} symbols)"

print(f"Refreshing cache: timeframe={timeframe}, mode={mode}, {label}")

# COMMAND ----------

# Initialize cache (spark mode = UC via Delta)
cache = MarketDataCache(mode="spark")

# COMMAND ----------

# Refresh in batches to avoid overwhelming the WebSocket connection
total_fetched = 0
total_inserted = 0

is_single = bool(symbol)

import secrets as _sec

if mode == "backfill":
    BATCH_SIZE = 1 if is_single else 5
    MAX_CONCURRENT = 1 if is_single else 1
    CHUNK_SIZE = 4000
    refresh_func = cache.refresh_multi_all
    refresh_kwargs = {"chunk_size": CHUNK_SIZE, "max_concurrent": MAX_CONCURRENT}
    print(f"Using paginated backfill: chunk_size={CHUNK_SIZE}, batch={BATCH_SIZE}, concurrency={MAX_CONCURRENT}")
else:
    BATCH_SIZE = 1 if is_single else 10
    MAX_CONCURRENT = 1 if is_single else 1
    BARS_COUNT = 500 if is_single else 2000
    refresh_func = cache.refresh_multi
    refresh_kwargs = {"bars_count": BARS_COUNT, "max_concurrent": MAX_CONCURRENT}
    print(f"Using incremental refresh: bars_count={BARS_COUNT}, batch={BATCH_SIZE}, concurrency={MAX_CONCURRENT}")

for i in range(0, len(symbols), BATCH_SIZE):
    batch = symbols[i:i + BATCH_SIZE]
    print(f"Batch {i // BATCH_SIZE + 1}/{(len(symbols) + BATCH_SIZE - 1) // BATCH_SIZE}: "
          f"{batch[0]}...{batch[-1]}")

    result = await refresh_func(batch, [timeframe], **refresh_kwargs)

    fails = 0
    for sym in batch:
        if sym in result and timeframe in result[sym]:
            r = result[sym][timeframe]
            total_fetched += r["fetched"]
            total_inserted += r["inserted"]
            if r.get("fetched", 0) == 0:
                fails += 1
                print(f"  !! {sym} returned 0 bars")
        else:
            fails += 1
            print(f"  !! {sym} missing from results")

    print(f"  -> fetched={total_fetched} inserted={total_inserted} (cumulative, {fails} failures in batch)")
    # Jittered sleep between batches to avoid rate-limit patterns
    await asyncio.sleep(5 + _sec.randbelow(3000) / 1000)

# COMMAND ----------

print(f"Done. Total fetched: {total_fetched}, total inserted: {total_inserted}")

# Log latest timestamps for a few symbols to confirm
check_symbols = symbols[:5]
rows = cache.latest_timestamps(check_symbols, [timeframe])
for r in rows:
    print(f"  {r['symbol']}: last bar = {r['latest']}")
