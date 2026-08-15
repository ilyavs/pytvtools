# Databricks notebook source
# MAGIC %md
# MAGIC # TVData Stress Test — Find the Limits
# MAGIC
# MAGIC Characterizes TVData WebSocket connection limits:
# MAGIC - **Max bars per request** per timeframe (1MB frame limit)
# MAGIC - **Pagination depth** (sequential `request_more_data` chunks)
# MAGIC - **Concurrent connection** capacity
# MAGIC - **Full symbol history** for stock/crypto/ETF symbols
# MAGIC
# MAGIC Results guide the `BARS_COUNT`, `chunk_size`, and `max_concurrent` settings
# MAGIC in cache refresh.

# COMMAND ----------

# MAGIC %pip install -q websockets

# COMMAND ----------

import sys, time, json, asyncio
sys.path.insert(0, "/Workspace/Users/sl.ilya1987@gmail.com/pytvtools-core/src")

from pytvtools_core.tvdata import TVData
from datetime import datetime, timezone, timedelta
def ts_dt(ts):
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=ts)

dbutils.widgets.text("symbol", "NASDAQ:AAPL")
dbutils.widgets.text("interval", "1D")

symbol = dbutils.widgets.get("symbol") or "NASDAQ:AAPL"
interval = dbutils.widgets.get("interval") or "1D"

print(f"Target: {symbol} {interval}")
print(f"TVData version: {TVData.__module__}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test 1: Binary-search max bars per single request
# MAGIC
# MAGIC Finds the largest `bars_count` that succeeds in one request.
# MAGIC The 1MB frame limit causes `websockets.exceptions.ConnectionClosedError`.

# COMMAND ----------

async def test_max_single(sym, iv, low=500, high=15000):
    best = low
    while low <= high:
        mid = (low + high) // 2
        try:
            async with TVData() as d:
                bars = await d.get_ohlcv(sym, iv, mid)
            if len(bars) > best:
                best = len(bars)
            low = mid + 1000
        except Exception as e:
            err = str(e)
            if "1009" in err or "frame" in err:
                high = mid - 1000
            elif "not found" in err.lower() or "no data" in err.lower():
                print(f"  {mid}: no data — {err[:80]}")
                return best
            else:
                print(f"  {mid}: other error — {err[:80]}")
                high = mid - 1000
    return best

print("=== Test 1: Max bars per single request ===")
results = {}
for iv in ["1", "5", "10", "15", "60", "D", "W", "M"]:
    try:
        max_bars = await test_max_single(symbol, iv)
        results[iv] = max_bars
        print(f"  {iv}: ~{max_bars} bars")
    except Exception as e:
        results[iv] = str(e)[:80]
        print(f"  {iv}: ERROR {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test 2: Pagination depth (full symbol history)
# MAGIC
# MAGIC Fetches all available bars via `request_more_data` pagination.
# MAGIC Reports total bars, date range, and number of chunk requests.

# COMMAND ----------

async def test_full_history(sym, iv, chunk=4000):
    t0 = time.time()
    try:
        async with TVData() as d:
            all_bars = await d.get_ohlcv_all(sym, iv, chunk_size=chunk)
    except Exception as e:
        return {"symbol": sym, "interval": iv, "bars": 0, "error": str(e)[:200], "elapsed_s": round(time.time() - t0, 1)}

    if all_bars:
        return {
            "symbol": sym, "interval": iv,
            "bars": len(all_bars), "chunks": None,
            "from": ts_dt(all_bars[0]["timestamp"]),
            "to": ts_dt(all_bars[-1]["timestamp"]),
            "elapsed_s": round(time.time() - t0, 1),
        }
    return {"symbol": sym, "interval": iv, "bars": 0, "elapsed_s": round(time.time() - t0, 1)}

print("=== Test 2: Full history per interval ===")
history_results = {}
for iv in ["1D", "1W", "1M"]:
    r = await test_full_history(symbol, iv)
    history_results[iv] = r
    if r["bars"]:
        print(f"  {iv}: {r['bars']} bars, {r['chunks']} chunks, {r['from']} -> {r['to']}, {r['elapsed_s']}s")
    else:
        print(f"  {iv}: ERROR — no data")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test 3: Concurrent connections
# MAGIC
# MAGIC Opens N concurrent connections to find the practical limit.
# MAGIC Reports success rate and timing.

# COMMAND ----------

async def test_concurrent(sym, iv, n=5, bars=1000):
    t0 = time.time()
    results = []
    async def fetch_one(i):
        try:
            async with TVData() as d:
                bars = await d.get_ohlcv(sym, iv, bars)
            return (i, "ok", len(bars))
        except Exception as e:
            return (i, "fail", str(e)[:60])
    outcomes = await asyncio.gather(*[fetch_one(i) for i in range(n)])
    elapsed = time.time() - t0
    ok = sum(1 for _, s, _ in outcomes if s == "ok")
    return {"attempted": n, "succeeded": ok, "failed": n - ok, "elapsed_s": round(elapsed, 1), "details": outcomes}

print("=== Test 3: Concurrent connection limits ===")
for n in [5, 10, 20, 50]:
    r = await test_concurrent(symbol, interval, n)
    print(f"  {n} concurrent: {r['succeeded']}/{r['attempted']} ok, {r['elapsed_s']}s")
    if r["failed"]:
        print(f"    Failures: {[d for d in r['details'] if d[2] != 'ok']}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test 4: Heavy symbols — full history for benchmarks
# MAGIC
# MAGIC Tests well-known high-bar-count symbols to establish baselines.

# COMMAND ----------

print("=== Test 4: Heavy symbol benchmarks (1D) ===")
heavy_symbols = ["NASDAQ:AAPL", "NASDAQ:MSFT", "NASDAQ:AMZN", "SP:SPX", "SPY", "NYSE:XOM", "NYSE:IBM", "BITSTAMP:BTCUSD", "BITSTAMP:ETHUSD"]
for sym in heavy_symbols:
    r = await test_full_history(sym, "1D")
    if r["bars"]:
        print(f"  {sym}: {r['bars']} bars, {r['chunks']} chunks, {r['from']} -> {r['to']}, {r['elapsed_s']}s")
    else:
        print(f"  {sym}: ERROR")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary Report
# MAGIC
# MAGIC Recommended settings for `cache_refresh.py` based on results:

# COMMAND ----------

print("=== SUMMARY ===")
print(f"Symbol: {symbol}")
print(f"Interval: {interval}")
print()
print("--- Test 1: Max bars per single request ---")
for iv, n in sorted(results.items()):
    print(f"  {iv}: ~{n}")
print()
print("--- Test 2: Full history per interval ---")
for iv, r in sorted(history_results.items()):
    if r["bars"]:
        print(f"  {iv}: {r['bars']} bars, {r['chunks']} chunks, {r['from']} -> {r['to']}")
    else:
        print(f"  {iv}: ERROR")
print()
print("--- Test 3: Concurrent connections ---")
print("  See per-test results above")
print()
print("--- Test 4: Heavy symbol benchmarks ---")
print("  See per-test results above")

bars_max_1D = results.get("D", "?")
bars_max_60 = results.get("60", "?")
print()
print(f"=== RECOMMENDED SETTINGS ===")
print(f"  BARS_COUNT (1D batch): {min(bars_max_1D - 500, 5000) if isinstance(bars_max_1D, int) else 5000}")
print(f"  BARS_COUNT (1D single): {min(bars_max_1D, 8000) if isinstance(bars_max_1D, int) else 8000}")
print(f"  TVData chunk_size (1D): 4000")
print(f"  Use get_ohlcv_all for full history: YES")

# Additional: test 5m and 10m pagination
print()
print("=== Test 5a: 5m pagination depth ===")
async with TVData() as d:
    try:
        bars_5m = await d.get_ohlcv_all("AAPL", "5", chunk_size=4000)
        if bars_5m:
            bars_5m.sort(key=lambda b: b["timestamp"])
            print(f"  5m total: {len(bars_5m)} bars")
            print(f"  Range: {ts_dt(bars_5m[0]['timestamp'])} -> {ts_dt(bars_5m[-1]['timestamp'])}")
            history_results["5m"] = {"bars": len(bars_5m), "from": str(ts_dt(bars_5m[0]['timestamp'])), "to": str(ts_dt(bars_5m[-1]['timestamp']))}
        else:
            print("  5m: 0 bars")
            history_results["5m"] = {"bars": 0}
    except Exception as e:
        print(f"  5m FAILED: {e}")
        history_results["5m"] = {"bars": 0, "error": str(e)[:200]}

# Additional: test 10m pagination (fallback: direct WebSocket if get_ohlcv_all fails)
print()
print("=== Test 5: 10m pagination depth ===")
async with TVData() as d:
    try:
        bars_10m = await d.get_ohlcv_all("AAPL", "10", chunk_size=546)
        if bars_10m:
            bars_10m.sort(key=lambda b: b["timestamp"])
            print(f"  10m total: {len(bars_10m)} bars")
            print(f"  Range: {ts_dt(bars_10m[0]['timestamp'])} -> {ts_dt(bars_10m[-1]['timestamp'])}")
            history_results["10m"] = {"bars": len(bars_10m), "from": str(ts_dt(bars_10m[0]['timestamp'])), "to": str(ts_dt(bars_10m[-1]['timestamp']))}
        else:
            print("  10m: 0 bars from get_ohlcv_all, trying direct fallback...")
            history_results["10m"] = {"bars": 0, "note": "get_ohlcv_all returned 0"}
    except Exception as e:
        print(f"  10m get_ohlcv_all FAILED: {e}")

if not history_results.get("10m", {}).get("bars"):
    import websockets
    from pytvtools_core.tvdata import _session_id, _frame, _HEARTBEAT_RE, _FRAME_RE
    WS_URL = "wss://data.tradingview.com/socket.io/websocket?from=chart%2F"
    HDRS = {"Origin": "https://www.tradingview.com", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}
    bars_10m_raw = []
    try:
        async with websockets.connect(WS_URL, additional_headers=HDRS, open_timeout=30, max_size=2**30, ping_interval=20) as ws:
            cs = _session_id("cs_")
            await ws.send(_frame({"m": "chart_create_session", "p": [cs, ""]}))
            sd = json.dumps({"symbol": "AAPL", "adjustment": "splits"})
            await ws.send(_frame({"m": "resolve_symbol", "p": [cs, "sds_sym_1", f"={sd}"]}))
            await asyncio.sleep(0.3)
            await ws.send(_frame({"m": "create_series", "p": [cs, "sds_1", "s1", "sds_sym_1", "10", 546, ""]}))

            bars_before = 0; waiting = False; pending = 0
            deadline = time.time() + 60
            while time.time() < deadline:
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
                if isinstance(raw, bytes): raw = raw.decode("utf-8")
                if _HEARTBEAT_RE.match(raw): await ws.send(raw); continue
                for item in _FRAME_RE.split(raw):
                    if not item: continue
                    if item.startswith("~h~"): await ws.send(item); continue
                    try: msg = json.loads(item)
                    except: continue
                    mt, p = msg.get("m"), msg.get("p", [])
                    if mt == "timescale_update" and len(p) >= 2:
                        for _, sd2 in p[1].items():
                            for s in sd2.get("s", []):
                                v = s.get("v", [])
                                if len(v) >= 5:
                                    bars_10m_raw.append({"t": v[0], "o": v[1], "h": v[2], "l": v[3], "c": v[4], "v": v[5] if len(v) > 5 else 0})
                    elif mt == "series_completed":
                        if waiting:
                            got = len(bars_10m_raw) - bars_before
                            if got == 0: break
                            remaining = pending - got
                            if remaining > 5:
                                need = min(remaining, 546)
                                bars_before = len(bars_10m_raw); pending = need
                                await ws.send(_frame({"m": "request_more_data", "p": [cs, "sds_1", need]}))
                                continue
                            waiting = False
                        bars_before = len(bars_10m_raw); pending = 546; waiting = True
                        await ws.send(_frame({"m": "request_more_data", "p": [cs, "sds_1", 546]}))
                        continue
        if bars_10m_raw:
            bars_10m_raw.sort(key=lambda b: b["t"])
            print(f"  10m direct: {len(bars_10m_raw)} bars")
            print(f"  Range: {ts_dt(bars_10m_raw[0]['t'])} -> {ts_dt(bars_10m_raw[-1]['t'])}")
            history_results["10m"] = {"bars": len(bars_10m_raw), "from": str(ts_dt(bars_10m_raw[0]['t'])), "to": str(ts_dt(bars_10m_raw[-1]['t'])), "method": "direct"}
        else:
            print("  10m direct: 0 bars")
    except Exception as e:
        print(f"  10m direct FAILED: {e}")
        history_results["10m"] = {"bars": 0, "error": str(e)[:200]}

dbutils.notebook.exit(json.dumps({
    "symbol": symbol,
    "interval": interval,
    "max_bars_per_request": {str(k): v for k, v in results.items()},
    "full_history": {str(k): {kk: str(vv) if hasattr(vv, "isoformat") else vv for kk, vv in v.items()} for k, v in history_results.items()},
}))
