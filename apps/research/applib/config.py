"""App configuration: symbol lists, indicator registry, DB settings."""

from __future__ import annotations

import os

from pytvtools_core.indicators import sma, ema, rsi, atr, bbands, macd


# ── Symbol lists ─────────────────────────────────────────────────────

WATCHLIST_GROUP: list[dict[str, str | list[str]]] = [
    {"name": "S&P 500 Sectors", "symbols": [
        "ARCA:XLK", "ARCA:XLC", "ARCA:XLY", "ARCA:XLP", "ARCA:XLE",
        "ARCA:XLF", "ARCA:XLV", "ARCA:XLI", "ARCA:XLB", "ARCA:XLU",
        "ARCA:XLRE",
    ]},
    {"name": "Crypto", "symbols": [
        "BITSTAMP:BTCUSD", "BITSTAMP:ETHUSD",
    ]},
    {"name": "Metals & Miners", "symbols": [
        "OANDA:XAUUSD", "OANDA:XAGUSD", "COINBASE:COPPER",
        "ARCA:GLD", "ARCA:SLV", "ARCA:GDX", "ARCA:GDXJ", "ARCA:SILJ",
        "ARCA:COPX", "ARCA:NEM", "ARCA:FCX", "ARCA:SCCO", "ARCA:WPM",
        "ARCA:FNV", "ARCA:BTG", "ARCA:AGI", "ARCA:KGC", "ARCA:HL",
        "ARCA:SSRM", "ARCA:AA", "ARCA:AAUKF", "ARCA:CENX", "ARCA:KALU",
        "ARCA:RIO", "ARCA:BHP", "ARCA:RGLD", "ARCA:SAND", "ARCA:PAAS",
        "ARCA:CDE", "ARCA:EXK", "ARCA:NG", "ARCA:AG",
    ]},
    {"name": "Index Futures", "symbols": [
        "CME_MINI:ES1!", "CME_MINI:NQ1!", "CBOT:YM1!",
        "CME_MINI:RTY1!", "EUREX:FDAX1!", "EUREX:FESX1!",
    ]},
    {"name": "Index CFDs", "symbols": [
        "SPCFD:SPX", "TVC:NDQ", "TVC:DJI", "TVC:RUT",
        "TVC:DAX", "TVC:UKX", "TVC:PX1", "TVC:NI225", "TVC:HSI",
    ]},
    {"name": "Index ETFs", "symbols": [
        "ARCA:SPY", "ARCA:QQQ", "ARCA:IWM", "ARCA:DIA",
        "ARCA:VTI", "ARCA:MAGS",
    ]},
    {"name": "Bonds", "symbols": [
        "FRED:US10Y", "FRED:US02Y", "FRED:US03M",
        "CBOT:TN1!", "CBOT:ZT1!",
        "ARCA:TLT",
    ]},
    {"name": "Oil", "symbols": [
        "NYMEX:CL1!", "NYMEX:WTI1!", "NYMEX:BN1!",
        "OANDA:WTICOUSD", "OANDA:BCOUSD",
    ]},
    {"name": "Uranium & Strategic", "symbols": [
        "ARCA:URA", "ARCA:URNM", "ARCA:REMX", "ARCA:UEC",
        "ARCA:UUUU", "ARCA:DMLR", "ARCA:CCJ", "ARCA:NXE",
        "ARCA:GLO", "ARCA:FCUUF", "ARCA:ISO", "ARCA:PDN",
        "ARCA:UROY", "ARCA:YCA", "ARCA:SPUT", "ARCA:SRUUF",
        "ARCA:MP", "ARCA:LYSDY", "ARCA:GXU", "ARCA:ILIKF",
        "ARCA:X", "ARCA:STLD",
    ]},
]


# ── Indicator registry ───────────────────────────────────────────────

IndicatorDef = dict[str, str | int | float | None]

INDICATORS: list[dict[str, IndicatorDef | list[dict]]] = [
    {
        "id": "sma",
        "name": "SMA",
        "params": [
            {"name": "period_short", "label": "Period (fast)", "type": "int", "default": 20, "min": 2},
            {"name": "period_long", "label": "Period (slow)", "type": "int", "default": 50, "min": 2},
        ],
    },
    {
        "id": "ema",
        "name": "EMA",
        "params": [
            {"name": "period_short", "label": "Period (fast)", "type": "int", "default": 20, "min": 2},
            {"name": "period_long", "label": "Period (slow)", "type": "int", "default": 50, "min": 2},
        ],
    },
    {
        "id": "rsi",
        "name": "RSI",
        "params": [
            {"name": "period", "label": "Period", "type": "int", "default": 14, "min": 2},
        ],
    },
    {
        "id": "atr",
        "name": "ATR",
        "params": [
            {"name": "period", "label": "Period", "type": "int", "default": 14, "min": 2},
        ],
    },
    {
        "id": "bbands",
        "name": "Bollinger Bands",
        "params": [
            {"name": "period", "label": "Period", "type": "int", "default": 20, "min": 2},
            {"name": "stddev", "label": "Std Dev", "type": "float", "default": 2.0, "min": 0.5},
        ],
    },
    {
        "id": "macd",
        "name": "MACD",
        "params": [
            {"name": "fast", "label": "Fast", "type": "int", "default": 12, "min": 2},
            {"name": "slow", "label": "Slow", "type": "int", "default": 26, "min": 2},
            {"name": "signal", "label": "Signal", "type": "int", "default": 9, "min": 2},
        ],
    },
]


# ── DB config ────────────────────────────────────────────────────────

WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
CATALOG = "workspace"
SCHEMA = "chartdata"
TABLE = f"{CATALOG}.{SCHEMA}.ohlcv"


# ── Chart defaults ───────────────────────────────────────────────────

TIMEFRAMES = [
    {"value": "1D", "label": "Daily"},
    {"value": "1W", "label": "Weekly"},
    {"value": "1M", "label": "Monthly"},
]

BAR_COUNTS = [100, 250, 500, 1000]
