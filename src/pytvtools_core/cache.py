"""
Market data cache — stores OHLCV data locally or in Unity Catalog.

Three modes:

- **spark** — in-Databricks, writes to ``workspace.chartdata.ohlcv`` via Spark MERGE.
- **sdk** — local, writes to UC via ``databricks-sdk`` Statement Execution API.
- **local** — no Databricks needed, writes partitioned Parquet files to a local dir.

Usage::

    from pytvtools.cache import MarketDataCache

    # Local Parquet (no Databricks)
    cache = MarketDataCache(mode="local", cache_dir="data/market_cache")
    await cache.refresh("NASDAQ:AAPL", "1D")
    rows = cache.query("NASDAQ:AAPL", "1D")

    # Databricks Spark
    cache = MarketDataCache(mode="spark")
    await cache.refresh("NASDAQ:AAPL", "1D")

    # Local with UC via SDK
    cache = MarketDataCache(mode="sdk", warehouse_id="...")
    await cache.refresh("NASDAQ:AAPL", "1D")
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING
if TYPE_CHECKING:
    from pytvtools_core.types import OHLCVBar
from urllib.parse import quote, unquote

import websockets

try:
    from pytvtools_core.tvdata import TVData
except ImportError:
    from tvdata import TVData  # standalone / direct import

# ---------------------------------------------------------------------------
#  UC defaults
# ---------------------------------------------------------------------------
_CATALOG = "workspace"
_SCHEMA = "chartdata"
_TABLE = f"{_CATALOG}.{_SCHEMA}.ohlcv"


# ---------------------------------------------------------------------------
#  Cache
# ---------------------------------------------------------------------------

class MarketDataCache:
    """Cache for TradingView OHLCV data.

    Parameters
    ----------
    mode:
        ``"local"`` — Parquet files on disk.
        ``"spark"`` — UC via Spark (in Databricks).
        ``"sdk"`` — UC via databricks-sdk (local).
    cache_dir:
        Required for ``"local"`` mode.  Data is stored as
        ``<cache_dir>/<symbol>/<timeframe>.parquet``.
    warehouse_id:
        Required for ``"sdk"`` mode.
    profile:
        Databricks CLI profile (default ``"DEFAULT"``).
    """

    def __init__(
        self,
        mode: str = "local",
        cache_dir: str | Path | None = None,
        warehouse_id: str | None = None,
        profile: str = "DEFAULT",
    ) -> None:
        self._mode = mode
        self._cache_dir = Path(cache_dir) if cache_dir else Path("data/market_cache")

        if mode == "local":
            self._init_local()
            self.query = self._query_local
        elif mode == "spark":
            self._init_spark()
            self.query = self._query_uc
        elif mode == "sdk":
            self._init_sdk(warehouse_id, profile)
            self.query = self._query_uc
        else:
            raise ValueError(f"Unknown mode: {mode}")

    # -- Init helpers -------------------------------------------------------

    def _init_local(self) -> None:
        import pyarrow as pa
        import pyarrow.parquet as pq
        self._pa = pa
        self._pq = pq

    def _init_spark(self) -> None:
        import importlib.util
        if importlib.util.find_spec("pyspark") is None:
            raise ImportError("spark mode requires PySpark — use mode='local' or 'sdk'")
        from pyspark.sql import SparkSession
        self._spark = SparkSession.builder.getOrCreate()
        self._ensure_table_uc()

    def _init_sdk(
        self, warehouse_id: str | None, profile: str
    ) -> None:
        if warehouse_id is None:
            raise ValueError("warehouse_id required in sdk mode")
        from databricks.sdk import WorkspaceClient
        self._ws = WorkspaceClient(profile=profile)
        self._warehouse_id = warehouse_id
        self._ensure_table_uc()

    def _ensure_table_uc(self) -> None:
        try:
            sql = f"CREATE SCHEMA IF NOT EXISTS {_CATALOG}.{_SCHEMA}"
            if self._mode == "spark":
                self._spark.sql(sql)
            else:
                from databricks.sdk.service.sql import Statement
                self._ws.statement_execution.execute_statement(
                    sql, warehouse_id=self._warehouse_id, wait_timeout="15s"
                ).result()
        except Exception:
            pass  # might already exist, ignore
        try:
            sql = f"""
                CREATE TABLE IF NOT EXISTS {_TABLE} (
                    symbol STRING,
                    timeframe STRING,
                    timestamp TIMESTAMP,
                    timestamp_str STRING,
                    open DOUBLE,
                    high DOUBLE,
                    low DOUBLE,
                    close DOUBLE,
                    volume DOUBLE,
                    _updated_at STRING
                )
                USING DELTA
                PARTITIONED BY (symbol, timeframe)
            """
            if self._mode == "spark":
                self._spark.sql(sql)
            else:
                from databricks.sdk.service.sql import Statement
                self._ws.statement_execution.execute_statement(
                    sql, warehouse_id=self._warehouse_id, wait_timeout="15s"
                ).result()
        except Exception:
            pass
        self._ensure_timestamp_str_uc()

    def _ensure_timestamp_str_uc(self) -> None:
        """Add timestamp_str column to UC table if missing."""
        try:
            sql = f"ALTER TABLE {_TABLE} ADD COLUMNS (timestamp_str STRING COMMENT 'Human-readable timestamp')"
            if self._mode == "spark":
                self._spark.sql(sql)
            else:
                from databricks.sdk.service.sql import Statement
                self._ws.statement_execution.execute_statement(
                    sql, warehouse_id=self._warehouse_id, wait_timeout="15s"
                ).result()
        except Exception:
            pass  # column already exists

    # ------------------------------------------------------------------
    #  Public API
    # ------------------------------------------------------------------

    async def refresh(
        self,
        symbol: str,
        timeframe: str,
        bars_count: int = 1500,
    ) -> dict[str, int]:
        """Fetch new bars and append/upsert into the cache.

        Returns ``{"fetched": N, "inserted": M}``.
        """
        latest_ts = self._latest_timestamp(symbol, timeframe)
        all_bars = await self._fetch(symbol, timeframe, bars_count)
        new_bars = [b for b in all_bars if b["timestamp"] > latest_ts] if latest_ts else all_bars
        if not new_bars:
            return {"fetched": len(all_bars), "inserted": 0}
        self._store_bars(symbol, timeframe, new_bars, bool(latest_ts))
        return {"fetched": len(all_bars), "inserted": len(new_bars)}

    async def refresh_all(
        self,
        symbol: str,
        timeframe: str,
        chunk_size: int = 4000,
    ) -> dict[str, int]:
        """Fetch ALL available bars via pagination, replacing existing data.

        Drops existing cache for (symbol, timeframe), fetches full history
        via ``get_ohlcv_all``, then does a fresh INSERT.

        Returns ``{"fetched": N, "inserted": M}``.
        """
        self._delete_bars(symbol, timeframe)
        all_bars = await self._fetch_all(symbol, timeframe, chunk_size)
        if not all_bars:
            return {"fetched": 0, "inserted": 0}
        self._store_bars(symbol, timeframe, all_bars, incremental=False)
        return {"fetched": len(all_bars), "inserted": len(all_bars)}

    async def refresh_multi(
        self,
        symbols: list[str],
        timeframes: list[str],
        bars_count: int = 1500,
        max_concurrent: int = 3,
    ) -> dict[str, dict[str, dict[str, int]]]:
        """Refresh multiple symbol/timeframe combos.

        Returns ``{symbol: {timeframe: {"fetched": N, "inserted": M}}}``.
        """
        sem = asyncio.Semaphore(max_concurrent)

        async def _one(sym: str, tf: str) -> tuple[str, str, dict[str, int]]:
            async with sem:
                return sym, tf, await self.refresh(sym, tf, bars_count)

        results: dict[str, dict[str, dict[str, int]]] = {}
        for sym, tf, res in await asyncio.gather(*[_one(s, tf) for s in symbols for tf in timeframes]):
            results.setdefault(sym, {})[tf] = res
        return results

    async def refresh_multi_all(
        self,
        symbols: list[str],
        timeframes: list[str],
        chunk_size: int = 4000,
        max_concurrent: int = 3,
    ) -> dict[str, dict[str, dict[str, int]]]:
        """Refresh multiple symbol/timeframe combos with full pagination.

        Uses ``refresh_all`` for each pair.  Best for initial backfill;
        switch to ``refresh_multi`` for incremental updates.

        Returns ``{symbol: {timeframe: {"fetched": N, "inserted": M}}}``.
        """
        sem = asyncio.Semaphore(max_concurrent)

        async def _one(sym: str, tf: str) -> tuple[str, str, dict[str, int]]:
            async with sem:
                return sym, tf, await self.refresh_all(sym, tf, chunk_size)

        results: dict[str, dict[str, dict[str, int]]] = {}
        for sym, tf, res in await asyncio.gather(*[_one(s, tf) for s in symbols for tf in timeframes]):
            results.setdefault(sym, {})[tf] = res
        return results

    def latest_timestamps(
        self,
        symbols: list[str] | None = None,
        timeframes: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Latest timestamp per symbol/timeframe pair."""
        if self._mode == "local":
            return self._latest_local(symbols, timeframes)
        return self._latest_uc(symbols, timeframes)

    # -- query is set in __init__ to _query_local or _query_uc

    # ------------------------------------------------------------------
    #  Fetch
    # ------------------------------------------------------------------

    @staticmethod
    async def _fetch(symbol: str, timeframe: str, count: int) -> list[OHLCVBar]:
        async with TVData() as tv:
            return await tv.get_ohlcv(symbol, timeframe, count)

    @staticmethod
    async def _fetch_all(symbol: str, timeframe: str, chunk_size: int) -> list[OHLCVBar]:
        for attempt in range(3):
            try:
                async with TVData() as tv:
                    return await tv.get_ohlcv_all(symbol, timeframe, chunk_size)
            except websockets.ConnectionClosed:
                if attempt == 2:
                    raise
                await asyncio.sleep(2 ** attempt)
        return []

    # ------------------------------------------------------------------
    #  Latest timestamp
    # ------------------------------------------------------------------

    def _delete_bars(self, symbol: str, timeframe: str) -> None:
        if self._mode == "local":
            path = self._cache_dir / _safe_name(symbol) / f"{timeframe}.parquet"
            if path.exists():
                path.unlink()
        else:
            sql = f"DELETE FROM {_TABLE} WHERE symbol = '{symbol}' AND timeframe = '{timeframe}'"
            if self._mode == "spark":
                self._spark.sql(sql)
            else:
                from databricks.sdk.service.sql import Statement
                self._ws.statement_execution.execute_statement(
                    sql, warehouse_id=self._warehouse_id, wait_timeout="30s"
                ).result()

    def _latest_timestamp(self, symbol: str, timeframe: str) -> float | None:
        rows = self.latest_timestamps([symbol], [timeframe])
        return rows[0]["latest"] if rows else None

    def _count_bars(self, symbol: str, timeframe: str) -> int:
        if self._mode == "local":
            path = self._cache_dir / _safe_name(symbol) / f"{timeframe}.parquet"
            if not path.exists():
                return 0
            return self._pq.read_table(str(path), columns=["timestamp"]).num_rows
        sql = f"SELECT count(*) AS n FROM {_TABLE} WHERE symbol = '{symbol}' AND timeframe = '{timeframe}'"
        rows = self._exec_uc(sql)
        return rows[0]["n"] if rows else 0

    # -- local --

    def _latest_local(
        self,
        symbols: list[str] | None = None,
        timeframes: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        syms = symbols or self._list_local_symbols()
        for sym in syms:
            tfs = timeframes or self._list_local_timeframes(sym)
            for tf in tfs:
                latest = self._read_latest_local(sym, tf)
                if latest is not None:
                    out.append({"symbol": sym, "timeframe": tf, "latest": latest})
        return out

    def _list_local_symbols(self) -> list[str]:
        if not self._cache_dir.is_dir():
            return []
        return [unquote(d.name) for d in self._cache_dir.iterdir() if d.is_dir()]

    def _list_local_timeframes(self, symbol: str) -> list[str]:
        d = self._cache_dir / _safe_name(symbol)
        if not d.is_dir():
            return []
        return [f.stem for f in d.glob("*.parquet")]

    def _read_latest_local(self, symbol: str, timeframe: str) -> float | None:
        path = self._cache_dir / _safe_name(symbol) / f"{timeframe}.parquet"
        if not path.exists():
            return None
        table = self._pq.read_table(path, columns=["timestamp"])
        return table.column("timestamp").to_pylist()[-1] if table.num_rows else None

    # -- UC (spark + sdk) --

    def _latest_uc(
        self,
        symbols: list[str] | None = None,
        timeframes: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        filters: list[str] = []
        if symbols:
            q = ", ".join(f"'{s}'" for s in symbols)
            filters.append(f"symbol IN ({q})")
        if timeframes:
            q = ", ".join(f"'{t}'" for t in timeframes)
            filters.append(f"timeframe IN ({q})")
        where = " AND ".join(filters) if filters else "1=1"
        sql = f"""
            SELECT symbol, timeframe, max(unix_timestamp(timestamp)) AS latest
            FROM {_TABLE}
            WHERE {where}
            GROUP BY symbol, timeframe
        """
        return self._exec_uc(sql)

    # ------------------------------------------------------------------
    #  Store
    # ------------------------------------------------------------------

    def _store_bars(
        self, symbol: str, timeframe: str, bars: list[dict], incremental: bool
    ) -> None:
        if self._mode == "local":
            self._store_local(symbol, timeframe, bars, incremental)
        elif self._mode == "spark":
            self._store_spark(symbol, timeframe, bars, incremental)
        else:
            self._store_sdk(symbol, timeframe, bars, incremental)

    # -- local parquet --

    def _store_local(
        self, symbol: str, timeframe: str, bars: list[dict], incremental: bool
    ) -> None:
        path = self._cache_dir / _safe_name(symbol)
        path.mkdir(parents=True, exist_ok=True)
        file = path / f"{timeframe}.parquet"

        ts_strs = [_fmt_tv_timestamp(b["timestamp"], timeframe) for b in bars]
        new_table = self._pa.table(
            {
                "timestamp": [b["timestamp"] for b in bars],
                "timestamp_str": ts_strs,
                "open": [float(b["open"]) for b in bars],
                "high": [float(b["high"]) for b in bars],
                "low": [float(b["low"]) for b in bars],
                "close": [float(b["close"]) for b in bars],
                "volume": [float(b["volume"]) for b in bars],
            }
        )

        if incremental and file.exists():
            existing = self._pq.read_table(str(file))
            combined = self._pa.concat_tables([existing, new_table])
            # dedup by timestamp
            combined = combined.sort_by("timestamp")
            ts_col = combined.column("timestamp").to_pylist()
            mask = [True] + [ts_col[i] != ts_col[i - 1] for i in range(1, len(ts_col))]
            combined = combined.filter(mask)
        else:
            combined = new_table

        self._pq.write_table(combined, str(file))

    # -- UC spark --

    def _store_spark(
        self, symbol: str, timeframe: str, bars: list[dict], incremental: bool
    ) -> None:
        now = datetime.now(timezone.utc)
        rows = [
            (
                symbol,
                timeframe,
                datetime.fromtimestamp(b["timestamp"], tz=timezone.utc),
                float(b["open"]),
                float(b["high"]),
                float(b["low"]),
                float(b["close"]),
                float(b["volume"]),
                now,
                _fmt_tv_timestamp(b["timestamp"], timeframe),
            )
            for b in bars
        ]
        df = self._spark.createDataFrame(rows, schema=(
            "symbol STRING, timeframe STRING, timestamp TIMESTAMP, "
            "open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, "
            "volume DOUBLE, _updated_at TIMESTAMP, timestamp_str STRING"
        ))
        df.createOrReplaceTempView("_new_bars")

        cols = "symbol, timeframe, timestamp, open, high, low, close, volume, _updated_at, timestamp_str"
        if incremental:
            self._spark.sql(f"""
                MERGE INTO {_TABLE} AS t
                USING _new_bars AS s
                ON t.symbol = s.symbol AND t.timeframe = s.timeframe AND t.timestamp = s.timestamp
                WHEN MATCHED THEN UPDATE SET
                    open = s.open, high = s.high, low = s.low,
                    close = s.close, volume = s.volume, _updated_at = s._updated_at,
                    timestamp_str = s.timestamp_str
                WHEN NOT MATCHED THEN INSERT ({cols})
                    VALUES ({cols})
            """)
        else:
            self._spark.sql(f"INSERT INTO {_TABLE} ({cols}) SELECT {cols} FROM _new_bars")

    # -- UC sdk --

    def _store_sdk(
        self, symbol: str, timeframe: str, bars: list[dict], incremental: bool
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        values: list[str] = []
        for b in bars:
            ts = _ts_to_str(b["timestamp"])
            tss = _fmt_tv_timestamp(b["timestamp"], timeframe)
            values.append(
                f"('{symbol}', '{timeframe}', timestamp '{ts}', '{tss}', "
                f"{b['open']}, {b['high']}, {b['low']}, {b['close']}, {b['volume']}, '{now}')"
            )
        if not values:
            return

        if incremental:
            sql = f"""
                MERGE INTO {_TABLE} AS t
                USING (VALUES {', '.join(values)})
                    AS s(symbol,timeframe,timestamp,timestamp_str,open,high,low,close,volume,_updated_at)
                ON t.symbol = s.symbol AND t.timeframe = s.timeframe AND t.timestamp = s.timestamp
                WHEN MATCHED THEN UPDATE SET
                    open = s.open, high = s.high, low = s.low,
                    close = s.close, volume = s.volume, _updated_at = s._updated_at
                WHEN NOT MATCHED THEN INSERT *
            """
        else:
            sql = f"""
                INSERT INTO {_TABLE}
                SELECT * FROM (VALUES {', '.join(values)})
                    AS s(symbol,timeframe,timestamp,timestamp_str,open,high,low,close,volume,_updated_at)
            """
        from databricks.sdk.service.sql import Statement
        self._ws.statement_execution.execute_statement(
            sql, warehouse_id=self._warehouse_id, wait_timeout="30s"
        ).result()

    # ------------------------------------------------------------------
    #  Query helpers
    # ------------------------------------------------------------------

    def _query_local(
        self,
        symbol: str,
        timeframe: str,
        since: float | None = None,
        until: float | None = None,
    ) -> list[OHLCVBar]:
        path = self._cache_dir / _safe_name(symbol) / f"{timeframe}.parquet"
        if not path.exists():
            return []
        table = self._pq.read_table(str(path))
        names = table.column_names
        rows: list[OHLCVBar] = []
        for row in zip(*[table.column(c).to_pylist() for c in names]):
            entry = dict(zip(names, row))
            # MyPy might complain about dictionary types here, but let's see.
            # Actually, `dict(zip(names, row))` is `dict[str, Any]` but we want it to be `OHLCVBar`.
            # I might need a cast or just accept it matches the structure.
            # Wait, OHLCVBar is a TypedDict. A plain dict isn't automatically OHLCVBar.
            # The brief just says "update type hint", not "fix all typing errors".
            ts = entry["timestamp"]
            if since is not None and ts < since:
                continue
            if until is not None and ts > until:
                continue
            rows.append(entry) # type: ignore
        return rows

    def _query_uc(
        self,
        symbol: str,
        timeframe: str,
        since: float | None = None,
        until: float | None = None,
    ) -> list[OHLCVBar]:
        where = f"symbol = '{symbol}' AND timeframe = '{timeframe}'"
        _add = []
        if since is not None:
            _add.append(f"timestamp >= timestamp_seconds({int(since)})")
        if until is not None:
            _add.append(f"timestamp <= timestamp_seconds({int(until)})")
        if _add:
            where += " AND " + " AND ".join(_add)
        sql = f"SELECT * FROM {_TABLE} WHERE {where} ORDER BY timestamp"
        return self._exec_uc(sql)

    def _exec_uc(self, sql: str) -> list[OHLCVBar]:
        if self._mode == "spark":
            rows = self._spark.sql(sql).collect()
            return [r.asDict() for r in rows] # type: ignore
        # sdk
        from databricks.sdk.service.sql import Statement
        resp = self._ws.statement_execution.execute_statement(
            sql, warehouse_id=self._warehouse_id, wait_timeout="30s",
        ).result()
        if resp.status and resp.status.state == Statement.StateCode.SUCCEEDED:
            if resp.result and resp.result.data_array:
                cols = [c.name for c in resp.manifest.schema.columns] if resp.manifest and resp.manifest.schema else []
                return [dict(zip(cols, row)) for row in resp.result.data_array] # type: ignore
        return []


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _ts_to_str(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _fmt_tv_timestamp(ts: float, timeframe: str) -> str:
    """Format a unix timestamp like TradingView does per timeframe."""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    tf = timeframe.upper()
    if tf.isdigit():
        return dt.strftime("%m/%d %H:%M")
    if tf == "W" or tf.endswith("W"):
        return dt.strftime("%m/%d/%Y")
    if tf == "M" or tf.endswith("M"):
        return dt.strftime("%b %Y")
    return dt.strftime("%m/%d/%Y")


def _safe_name(symbol: str) -> str:
    return quote(symbol, safe="")

