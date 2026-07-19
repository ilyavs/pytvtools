"""Data fetching from the UC cache table via Databricks SQL."""

from __future__ import annotations

import os
from typing import Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config

from applib.config import TABLE, WAREHOUSE_ID


def _get_warehouse_id() -> str:
    wid = WAREHOUSE_ID or os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
    if not wid:
        w = WorkspaceClient()
        whs = w.warehouses.list()
        for wh in whs:
            if wh.state == "RUNNING":
                return wh.id
        raise RuntimeError("No running SQL warehouse found")
    return wid


def fetch_bars(
    symbol: str,
    timeframe: str,
    bars_count: int = 500,
) -> list[dict[str, Any]]:
    """Fetch OHLCV bars from the Unity Catalog cache table.

    Returns list of dicts matching ``OHLCVBar`` (``timestamp`` as unix
    float, plus ``open``/``high``/``low``/``close``/``volume``).
    """
    cfg = Config()
    wid = _get_warehouse_id()
    w = WorkspaceClient()

    stmt = w.statement_execution.execute_statement(
        statement=f"""
        SELECT
            UNIX_TIMESTAMP(timestamp) AS ts,
            open, high, low, close, volume
        FROM {TABLE}
        WHERE symbol = '{symbol.replace("'", "''")}'
          AND timeframe = '{timeframe}'
        ORDER BY timestamp ASC
        LIMIT {int(bars_count)}
        """,
        warehouse_id=wid,
        byte_limit=50 * 1024 * 1024,
    )

    result = w.statement_execution.wait(stmt.statement_execution_id)
    manifest = result.manifest
    data = result.result.data_array or []

    if not manifest or not data:
        return []

    columns = [c.name for c in manifest.schema.columns]

    bars: list[dict[str, Any]] = []
    for row in data:
        row_dict = dict(zip(columns, row))
        bars.append({
            "timestamp": float(row_dict["ts"]),
            "open": float(row_dict["open"]),
            "high": float(row_dict["high"]),
            "low": float(row_dict["low"]),
            "close": float(row_dict["close"]),
            "volume": float(row_dict["volume"]),
        })

    return bars
