"""FastAPI routes for the research app."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from applib.config import WATCHLIST_GROUP, INDICATORS, TIMEFRAMES, BAR_COUNTS
from applib.data import fetch_bars
from applib.compute import compute_indicators, build_chart_html

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "watchlists": WATCHLIST_GROUP,
            "indicators": INDICATORS,
            "timeframes": TIMEFRAMES,
            "bar_counts": BAR_COUNTS,
        },
    )


@router.get("/api/config")
async def api_config():
    return {
        "watchlists": WATCHLIST_GROUP,
        "indicators": INDICATORS,
        "timeframes": TIMEFRAMES,
        "bar_counts": BAR_COUNTS,
    }


@router.post("/api/chart")
async def api_chart(
    symbol: str = Form(...),
    timeframe: str = Form("1D"),
    bars_count: int = Form(500),
    indicators_json: str = Form("{}"),
):
    """Build and return a chart HTML page.

    *indicators_json* is a JSON string mapping indicator_id -> {params}.
    """
    selected: dict[str, dict[str, Any]] = json.loads(indicators_json)

    bars = fetch_bars(symbol, timeframe, bars_count)
    if not bars:
        return JSONResponse({
            "chart_html": "<html><body><h1>No data</h1></body></html>",
            "bars_count": 0,
        })

    # Add symbol to bars for chart title
    for b in bars:
        b["symbol"] = symbol

    indicator_groups = compute_indicators(bars, selected)
    chart_html = build_chart_html(bars, indicator_groups, timeframe)

    return {
        "chart_html": chart_html,
        "bars_count": len(bars),
    }


@router.get("/api/symbols")
async def api_symbols():
    flat: list[dict[str, str]] = []
    for group in WATCHLIST_GROUP:
        for sym in group["symbols"]:
            flat.append({"symbol": sym, "group": group["name"]})
    return {"symbols": flat}
