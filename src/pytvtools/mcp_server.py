"""
Optional MCP server — exposes pytvtools as MCP tools for agent use.

Usage:
    pip install pytvtools[mcp]
    pytvtools-mcp
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys

logging.basicConfig(level=logging.WARNING)

try:
    from mcp.server import Server, NotificationOptions
    from mcp.server.models import InitializationOptions
    from mcp.types import Tool, TextContent
    import mcp.server.stdio
except ImportError:
    sys.exit("Install: pip install pytvtools[mcp]")

from pytvtools import TV, wait_for_cdp

server = Server("pytvtools")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_state",
            description="Current symbol, timeframe, chart type",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="set_symbol",
            description="Change the chart symbol",
            inputSchema={
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
            },
        ),
        Tool(
            name="set_timeframe",
            description="Change timeframe (D, 60, 15, 5, 1, W, M)",
            inputSchema={
                "type": "object",
                "properties": {"timeframe": {"type": "string"}},
                "required": ["timeframe"],
            },
        ),
        Tool(
            name="get_ohlcv",
            description="Get OHLCV bars. Use summary=true for compact stats.",
            inputSchema={
                "type": "object",
                "properties": {
                    "count": {"type": "number", "default": 100},
                    "summary": {"type": "boolean", "default": False},
                },
            },
        ),
        Tool(
            name="get_study_values",
            description="Current values from all visible indicators",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_quote",
            description="Real-time quote for the current or specified symbol",
            inputSchema={
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
            },
        ),
        Tool(
            name="get_pine_lines",
            description="Horizontal price levels from Pine indicators",
            inputSchema={
                "type": "object",
                "properties": {"study_filter": {"type": "string"}},
            },
        ),
        Tool(
            name="get_pine_labels",
            description="Text labels from Pine indicators",
            inputSchema={
                "type": "object",
                "properties": {
                    "study_filter": {"type": "string"},
                    "max_labels": {"type": "number", "default": 50},
                },
            },
        ),
        Tool(
            name="capture_screenshot",
            description="Capture chart screenshot as base64 PNG",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="batch",
            description="Scan multiple symbols/timeframes",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbols": {"type": "array", "items": {"type": "string"}},
                    "timeframes": {"type": "array", "items": {"type": "string"}},
                    "action": {
                        "type": "string",
                        "enum": ["ohlcv", "studies"],
                        "default": "ohlcv",
                    },
                },
                "required": ["symbols", "timeframes"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    await wait_for_cdp(timeout=5)
    async with TV() as tv:
        try:
            if name == "get_state":
                result = await tv.get_state()
            elif name == "set_symbol":
                await tv.set_symbol(arguments["symbol"])
                result = {"ok": True}
            elif name == "set_timeframe":
                await tv.set_timeframe(arguments["timeframe"])
                result = {"ok": True}
            elif name == "get_ohlcv":
                result = await tv.get_ohlcv(
                    count=arguments.get("count", 100),
                    summary=arguments.get("summary", False),
                )
            elif name == "get_study_values":
                result = await tv.get_study_values()
            elif name == "get_quote":
                result = await tv.get_quote(arguments.get("symbol"))
            elif name == "get_pine_lines":
                result = await tv.get_pine_lines(arguments.get("study_filter"))
            elif name == "get_pine_labels":
                result = await tv.get_pine_labels(
                    study_filter=arguments.get("study_filter"),
                    max_labels=arguments.get("max_labels", 50),
                )
            elif name == "capture_screenshot":
                result = {"data": (await tv.capture_screenshot())[:80] + "..."}
            elif name == "batch":
                result = await tv.batch(
                    symbols=arguments["symbols"],
                    timeframes=arguments["timeframes"],
                    action=arguments.get("action", "ohlcv"),
                )
            else:
                raise ValueError(f"Unknown tool: {name}")

            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except Exception as e:
            return [TextContent(type="text", text=json.dumps({"error": str(e)}, indent=2))]


async def main():
    async with mcp.server.stdio.stdio_server() as (read, write):
        await server.run(
            read, write, InitializationOptions(
                server_name="pytvtools",
                server_version="0.1.0",
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
