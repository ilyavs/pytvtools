"""Multi-symbol data collector for TradingView — batch fetch + parquet export.

Wraps ``TV.batch()`` with:
- Configurable symbol / timeframe lists
- Merge of OHLCV + study data into flat records
- Parquet export for post-hoc analysis in a separate project

Usage::

    from pytvtools import TV, Collector, CollectorConfig

    config = CollectorConfig(
        symbols=["BINANCE:BTCUSDT", "NASDAQ:AAPL"],
        timeframes=["1D", "60"],
        actions=["ohlcv"],
    )
    collector = Collector(config)
    async with TV() as tv:
        result = await collector.run(tv)
    path = collector.export_parquet("data.parquet")
"""

from __future__ import annotations

import dataclasses
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from pytvtools.tv import TV

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CollectorConfig:
    """Configuration for a multi-symbol data collection.

    Attributes
    ----------
    symbols : list[str]
        TradingView symbol strings (e.g. ``"BINANCE:BTCUSDT"``).
    timeframes : list[str]
        Timeframe strings (``"1D"``, ``"60"``, ``"15"``, etc.)
    actions : list[str] | None
        Which actions to run.  ``None`` (default) means both
        ``["ohlcv", "studies"]``.  Pass ``["ohlcv"]`` for a faster
        OHLCV-only collection.
    """
    symbols: list[str]
    timeframes: list[str]
    actions: list[str] | None = None

    def __post_init__(self) -> None:
        if not self.actions:
            self.actions = ["ohlcv", "studies"]
        for a in self.actions:
            if a not in ("ohlcv", "studies"):
                raise ValueError(
                    f"Unknown action {a!r} — expected 'ohlcv' or 'studies'"
                )


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CollectResult:
    """Merged output of a multi-symbol data collection.

    Attributes
    ----------
    records : list[dict[str, Any]]
        Flat records, one per symbol x timeframe.
        Each record contains ``symbol``, ``timeframe``, ``scan_ts``,
        plus ``ohlcv_*`` keys and per-study latest-value keys.
    symbols_total : int
    symbols_failed : list[str]
        Symbols that could not be collected after all retries.
    start_ts : datetime
    end_ts : datetime
    """
    records: list[dict[str, Any]]
    symbols_total: int
    symbols_failed: list[str]
    start_ts: datetime
    end_ts: datetime


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class Collector:
    """Fetch data across multiple symbols/timeframes and export to parquet.

    Typical pipeline::

        collector = Collector(config)
        async with TV() as tv:
            result = await collector.run(tv)
        collector.export_parquet("output/data.parquet")
    """

    def __init__(self, config: CollectorConfig) -> None:
        self.config = config
        actions = list(config.actions or ["ohlcv", "studies"])
        self._config_actions = actions
        want_both = {"ohlcv", "studies"}.issubset(set(actions))
        self._batch_action = "all" if want_both else actions[0]
        self._result: CollectResult | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self, tv: TV) -> CollectResult:
        """Execute the data collection and return merged results."""
        start_ts = datetime.now(timezone.utc)
        logger.info(
            "Collector: fetching %d symbols x %d timeframes, action=%s",
            len(self.config.symbols),
            len(self.config.timeframes),
            self._batch_action,
        )

        merged: dict[tuple[str, str], dict[str, Any]] = {}
        per_sym_failures: dict[str, set[str]] = {sym: set() for sym in self.config.symbols}

        raw = await tv.batch(self.config.symbols, self.config.timeframes, self._batch_action)
        for sym, tf_data in raw.items():
            for tf, val in tf_data.items():
                if val is None:
                    per_sym_failures[sym].add(tf)
                    continue
                key = (sym, tf)
                if key not in merged:
                    merged[key] = {"symbol": sym, "timeframe": tf, "scan_ts": start_ts}
                if self._batch_action == "all":
                    if not isinstance(val, dict):
                        logger.warning(
                            "Collector: unexpected val type for %s/%s: %s",
                            sym, tf, type(val).__name__,
                        )
                        per_sym_failures[sym].add(tf)
                        continue
                    ohlcv_val = val.get("ohlcv")
                    studies_val = val.get("studies")
                    if ohlcv_val is not None:
                        self._merge_ohlcv(merged[key], ohlcv_val)
                    if studies_val:
                        self._merge_studies(merged[key], studies_val)
                    if ohlcv_val is None and not studies_val:
                        per_sym_failures[sym].add(tf)
                elif self._batch_action == "ohlcv":
                    self._merge_ohlcv(merged[key], val)
                else:
                    self._merge_studies(merged[key], val)

        symbols_failed = [
            sym for sym in self.config.symbols
            if len(per_sym_failures[sym]) == len(self.config.timeframes)
        ]

        records = list(merged.values())
        end_ts = datetime.now(timezone.utc)

        result = CollectResult(
            records=records,
            symbols_total=len(self.config.symbols),
            symbols_failed=sorted(symbols_failed),
            start_ts=start_ts,
            end_ts=end_ts,
        )
        self._result = result

        logger.info(
            "Collector: done — %d records, %d/%d symbols failed",
            len(records),
            len(symbols_failed),
            len(self.config.symbols),
        )
        return result

    def export_parquet(
        self,
        path: str | Path,
        *,
        overwrite: bool = False,
    ) -> Path:
        """Flatten collected data to a Parquet file.

        Parameters
        ----------
        path : str | Path
            Output path.  ``.parquet`` extension is added if missing.
        overwrite : bool
            Allow overwriting an existing file (default ``False``).

        Returns
        -------
        Path
            The resolved output path.
        """
        if self._result is None:
            raise RuntimeError("Call run() before export_parquet()")

        path = Path(path)
        if path.suffix.lower() != ".parquet":
            path = path.with_suffix(".parquet")
        if path.exists() and not overwrite:
            raise FileExistsError(f"{path} exists — set overwrite=True to replace")

        records = self._result.records
        if not records:
            logger.warning("Collector: no records to export — writing empty file")
            table = _empty_table()
            pq.write_table(table, path)
            return path

        table = _records_to_table(records)
        pq.write_table(table, path, compression="zstd")
        logger.info("Collector: exported %d records to %s", len(records), path)
        return path

    def export_json(
        self,
        path: str | Path,
        *,
        overwrite: bool = False,
    ) -> Path:
        """Export collected data as newline-delimited JSON."""
        if self._result is None:
            raise RuntimeError("Call run() before export_json()")

        path = Path(path)
        if path.exists() and not overwrite:
            raise FileExistsError(f"{path} exists — set overwrite=True to replace")

        with open(path, "w", encoding="utf-8") as f:
            for rec in self._result.records:
                f.write(json.dumps(rec, default=str) + "\n")
        logger.info("Collector: exported %d records to %s", len(self._result.records), path)
        return path

    # ------------------------------------------------------------------
    # Merging helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_ohlcv(record: dict[str, Any], ohlcv: dict[str, Any]) -> None:
        for k, v in ohlcv.items():
            record[f"ohlcv_{k}"] = v

    @staticmethod
    def _merge_studies(record: dict[str, Any], studies: dict[str, Any]) -> None:
        for name, info in studies.items():
            if isinstance(info, dict) and "values" in info:
                vals = info["values"]
                if vals:
                    record[f"st_{name}"] = vals[-1]["value"]


# ---------------------------------------------------------------------------
# Parquet helpers
# ---------------------------------------------------------------------------


def _col_type(key: str) -> tuple[Any, type]:
    if key in ("symbol", "timeframe"):
        return pa.utf8(), str
    if key == "scan_ts":
        return pa.timestamp("us", tz="UTC"), datetime
    if key in ("ohlcv_count", "ohlcv_avg_volume"):
        return pa.int64(), int
    return pa.float64(), float


def _safe(values: list[Any], py_type: type) -> list[Any]:
    result = []
    for v in values:
        if v is None:
            result.append(None)
            continue
        if py_type is float:
            try:
                result.append(float(v))
            except (TypeError, ValueError):
                result.append(None)
        elif py_type is int:
            try:
                result.append(int(v))
            except (TypeError, ValueError):
                result.append(None)
        elif py_type is str:
            result.append(str(v))
        elif py_type is datetime:
            if isinstance(v, datetime):
                result.append(v)
            elif isinstance(v, (int, float)):
                result.append(datetime.fromtimestamp(v, tz=timezone.utc))
            else:
                result.append(None)
        else:
            result.append(None)
    return result


def _records_to_table(records: list[dict[str, Any]]) -> pa.Table:
    all_keys: list[str] = []
    seen: set[str] = set()
    for rec in records:
        for k in rec:
            if k not in seen:
                all_keys.append(k)
                seen.add(k)

    arrays: list[pa.Array] = []
    fields: list[pa.Field] = []

    for key in all_keys:
        values = [rec.get(key) for rec in records]
        pa_type, py_type = _col_type(key)
        clean = _safe(values, py_type)
        arrays.append(pa.array(clean, type=pa_type))
        fields.append(pa.field(key, pa_type))

    return pa.Table.from_arrays(arrays, schema=pa.schema(fields))


def _empty_table() -> pa.Table:
    schema = pa.schema([
        pa.field("symbol", pa.utf8()),
        pa.field("timeframe", pa.utf8()),
        pa.field("scan_ts", pa.timestamp("us", tz="UTC")),
    ])
    return pa.table({f.name: pa.array([], type=f.type) for f in schema})
