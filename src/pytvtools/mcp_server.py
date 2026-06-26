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
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.WARNING)

try:
    from mcp.server import Server, NotificationOptions
    from mcp.server.models import InitializationOptions
    from mcp.types import Tool, TextContent
    import mcp.server.stdio
except ImportError:
    sys.exit("Install: pip install pytvtools[mcp]")

from pytvtools import TV, TVData, wait_for_cdp

server = Server("pytvtools")

# --------------------------------------------------------------------------
# Credential resolution
# --------------------------------------------------------------------------

def _resolve_credentials(profile: str | None = None) -> dict[str, str] | None:
    """Resolve TradingView credentials for a named profile.

    Only ``profiles.<name>`` in the config file is checked — there is no
    root-level ``username`` / ``password`` fallback.  If you want env-var
    or manual mode, omit the ``profile`` argument.

    Resolution order:

    1. **Named profile in config** — ``profiles.<name>.username`` /
       ``profiles.<name>.password`` in ``~/.tv/config`` (or ``$TV_CONFIG_PATH``).
       Only checked when ``profile`` is provided.
    2. **Environment variables** — ``TV_USERNAME`` / ``TV_PASSWORD``.
    3. **Manual mode** — return ``None``, caller opens sign-in page.

    Parameters
    ----------
    profile : str or None
        Named profile under the ``profiles`` key in the config file.
        Must be explicitly provided to use config-file credentials.

    Returns
    -------
    dict or None
        ``{"username": …, "password": …}`` or ``None``.
    """
    if profile:
        config_path = os.environ.get("TV_CONFIG_PATH", str(Path.home() / ".tv" / "config"))
        try:
            with open(config_path) as f:
                cfg = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            cfg = None
        if cfg:
            p_cfg = (cfg.get("profiles") or {}).get(profile) or {}
            u = p_cfg.get("username", "")
            p = p_cfg.get("password", "")
            if u and p:
                return {"username": u, "password": p}

    u = os.environ.get("TV_USERNAME", "")
    p = os.environ.get("TV_PASSWORD", "")
    if u and p:
        return {"username": u, "password": p}

    return None


async def _test_profile(tv, name: str, creds: dict[str, str]) -> dict:
    """Try logging in with a single profile and report detailed results."""
    import asyncio

    # Navigate away from chart so login actually shows the form
    await tv._eval("window.location.href = 'about:blank'")
    await asyncio.sleep(0.5)

    try:
        result = await tv.login(
            username=creds["username"],
            password=creds["password"],
            timeout=45,
        )
    except Exception as e:
        return {"profile": name, "status": "error", "error": str(e)[:300]}

    await asyncio.sleep(2)
    url = await tv._eval("window.location.href")
    page_text = await tv._eval("document.body.innerText.substring(0, 600)")
    has_captcha = "captcha" in (page_text or "").lower()
    has_2fa = any(t in (page_text or "").lower() for t in ["2fa", "two-factor", "two factor", "authenticator", "verification code"])

    await tv._eval("window.location.href = 'https://www.tradingview.com/chart/'")
    await asyncio.sleep(3)
    still_logged_in = await tv.is_logged_in()

    return {
        "profile": name,
        "login_result": result,
        "url_after": (url or "")[:120],
        "page_clues": (page_text or "")[:300],
        "captcha_detected": has_captcha,
        "2fa_detected": has_2fa,
        "logged_in_after": still_logged_in,
    }


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
            name="get_ohlcv_fast",
            description="FAST OHLCV via direct WebSocket (no Chrome/ CDP needed). Supports any symbol/interval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Symbol in EXCHANGE:SYMBOL format, e.g. NASDAQ:AAPL"},
                    "interval": {"type": "string", "default": "1D", "description": "Timeframe (1, 5, 15, 60, D, W, M)"},
                    "bars_count": {"type": "number", "default": 100, "description": "Number of bars (max 5000 for free tier)"},
                    "summary": {"type": "boolean", "default": False},
                },
                "required": ["symbol"],
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
            name="set_chart_type",
            description="Change chart type (Candles=1, Line=2, Area=3)",
            inputSchema={
                "type": "object",
                "properties": {"chart_type": {"type": ["integer", "string"], "description": "Candles=1, Line=2, Area=3"}},
                "required": ["chart_type"],
            },
        ),
        Tool(
            name="get_visible_range",
            description="Visible date range from the chart",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="scroll_to_date",
            description="Jump the chart to a specific date",
            inputSchema={
                "type": "object",
                "properties": {"date": {"type": "string", "description": "ISO date (2025-01-15) or unix timestamp"}},
                "required": ["date"],
            },
        ),
        Tool(
            name="pine_set_source",
            description="Set Pine Script source in the editor",
            inputSchema={
                "type": "object",
                "properties": {"source": {"type": "string"}},
                "required": ["source"],
            },
        ),
        Tool(
            name="pine_compile",
            description="Compile Pine Script and return errors",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="pine_get_errors",
            description="Read Pine Script compilation errors from Monaco markers",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="pine_get_editor_source",
            description="Read the current Pine Script source from the editor",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="pine_close_editor",
            description="Close the Pine Script editor panel",
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
        Tool(
            name="search_indicators",
            description="Search for indicators by keyword. Returns list of {id, name}.",
            inputSchema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        ),
        Tool(
            name="add_indicator",
            description="Add an indicator by study ID or display name. Returns entity ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "indicator": {"type": "string", "description": "Study ID (STD;RSI, STD;SMA, RSI@tv-basicstudies) or display name (Relative Strength Index)"},
                    "inputs": {"type": "object", "description": "Optional input overrides, e.g. {\"length\": 20}"},
                },
                "required": ["indicator"],
            },
        ),
        Tool(
            name="remove_indicator",
            description="Remove an indicator by entity ID.",
            inputSchema={
                "type": "object",
                "properties": {"entity_id": {"type": "string"}},
                "required": ["entity_id"],
            },
        ),
        Tool(
            name="remove_all_indicators",
            description="Remove all indicators from the chart.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_indicator_count",
            description="Number of indicators currently on the chart.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="set_indicator_inputs",
            description="Change input values on an existing indicator.",
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string"},
                    "inputs": {"type": "object"},
                },
                "required": ["entity_id", "inputs"],
            },
        ),
        Tool(
            name="get_indicator_data",
            description="Get ALL historical plot data for an indicator by entity ID. Returns every bar for every plot.",
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string", "description": "Entity ID from add_indicator"},
                },
                "required": ["entity_id"],
            },
        ),
        Tool(
            name="list_templates",
            description="List saved indicator templates (optional tab: my templates, technicals, financials).",
            inputSchema={
                "type": "object",
                "properties": {
                    "tab": {"type": "string", "description": "Tab name: my templates, technicals, financials"},
                },
            },
        ),
        Tool(
            name="apply_template",
            description="Apply a saved indicator template by name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Template name"},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="replay_start",
            description="Start bar replay mode, optionally at a specific date.",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "ISO date (2024-01-15) or omit for first available"},
                },
            },
        ),
        Tool(
            name="replay_stop",
            description="Stop replay and return to realtime.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="replay_status",
            description="Get current replay mode state.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="replay_step",
            description="Advance one bar in replay mode.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="replay_autoplay",
            description="Toggle autoplay in replay mode, optionally set speed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "speed": {"type": "number", "description": "Autoplay delay in ms (lower=faster). Omit to just toggle."},
                },
            },
        ),
        Tool(
            name="is_logged_in",
            description="Check if currently logged in to TradingView.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="login",
            description="Log in to TradingView. Resolves credentials from ~/.tv/config (profiles.<name>), TV_USERNAME/TV_PASSWORD env vars, or falls back to manual mode.",
            inputSchema={
                "type": "object",
                "properties": {
                    "timeout": {"type": "number", "description": "Max seconds to wait (default 120)"},
                    "profile": {"type": "string", "description": "Named profile under `profiles` key in ~/.tv/config"},
                },
            },
        ),
        Tool(
            name="test_profiles",
            description="Try every profile in ~/.tv/config and report results.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="logout",
            description="Log out of the current TradingView account.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="dismiss_ad",
            description="Dismiss overlay ads on the chart.",
            inputSchema={"type": "object", "properties": {}},
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
            elif name == "get_ohlcv_fast":
                async with TVData() as d:
                    result = await d.get_ohlcv(
                        symbol=arguments["symbol"],
                        interval=arguments.get("interval", "1D"),
                        bars_count=arguments.get("bars_count", 100),
                        summary=arguments.get("summary", False),
                    )
            elif name == "get_ohlcv":
                result = await tv.get_ohlcv(
                    count=arguments.get("count", 100),
                    summary=arguments.get("summary", False),
                )
            elif name == "get_study_values":
                result = await tv.get_study_values()
            elif name == "get_quote":
                result = await tv.get_quote()
            elif name == "get_pine_lines":
                result = await tv.get_pine_lines(arguments.get("study_filter"))
            elif name == "get_pine_labels":
                result = await tv.get_pine_labels(
                    study_filter=arguments.get("study_filter"),
                    max_labels=arguments.get("max_labels", 50),
                )
            elif name == "capture_screenshot":
                result = {"data": await tv.capture_screenshot()}
            elif name == "set_chart_type":
                await tv.set_chart_type(arguments["chart_type"])
                result = {"ok": True}
            elif name == "get_visible_range":
                result = await tv.get_visible_range()
            elif name == "scroll_to_date":
                await tv.scroll_to_date(arguments["date"])
                result = {"ok": True}
            elif name == "pine_set_source":
                await tv.pine_set_source(arguments["source"])
                result = {"ok": True}
            elif name == "pine_compile":
                result = await tv.pine_compile()
            elif name == "pine_get_errors":
                result = {"errors": await tv.pine_get_errors()}
            elif name == "pine_get_editor_source":
                result = {"source": await tv.pine_get_editor_source()}
            elif name == "pine_close_editor":
                result = {"closed": await tv.pine_close_editor()}
            elif name == "batch":
                result = await tv.batch(
                    symbols=arguments["symbols"],
                    timeframes=arguments["timeframes"],
                    action=arguments.get("action", "ohlcv"),
                )
            elif name == "search_indicators":
                result = await tv.search_indicators(arguments["query"])
            elif name == "add_indicator":
                result = await tv.add_indicator(
                    indicator=arguments["indicator"],
                    inputs=arguments.get("inputs"),
                )
            elif name == "remove_indicator":
                await tv.remove_indicator(arguments["entity_id"])
                result = {"ok": True}
            elif name == "remove_all_indicators":
                await tv.remove_all_indicators()
                result = {"ok": True}
            elif name == "get_indicator_count":
                result = {"count": await tv.get_indicator_count()}
            elif name == "set_indicator_inputs":
                await tv.set_indicator_inputs(
                    entity_id=arguments["entity_id"],
                    inputs=arguments["inputs"],
                )
                result = {"ok": True}
            elif name == "get_indicator_data":
                result = await tv.get_indicator_data(
                    entity_id=arguments["entity_id"],
                )
            elif name == "list_templates":
                result = await tv.list_templates(tab=arguments.get("tab"))
            elif name == "apply_template":
                await tv.apply_template(
                    name=arguments["name"],
                )
                result = {"ok": True}
            elif name == "replay_start":
                result = await tv.replay_start(date=arguments.get("date"))
            elif name == "replay_stop":
                result = await tv.replay_stop()
            elif name == "replay_status":
                result = await tv.replay_status()
            elif name == "replay_step":
                result = await tv.replay_step()
            elif name == "is_logged_in":
                result = {"logged_in": await tv.is_logged_in()}
            elif name == "login":
                profile = arguments.get("profile")
                creds = _resolve_credentials(profile=profile)
                if creds:
                    result = await tv.login(
                        username=creds["username"],
                        password=creds["password"],
                        timeout=arguments.get("timeout", 120),
                        force=bool(profile),
                    )
                else:
                    result = await tv.login(timeout=arguments.get("timeout", 120))
            elif name == "test_profiles":
                import json as _json, os as _os
                from pathlib import Path as _Path
                config_path = _os.environ.get("TV_CONFIG_PATH", str(_Path.home() / ".tv" / "config"))
                try:
                    with open(config_path) as f:
                        cfg = _json.load(f)
                except Exception as e:
                    result = {"error": f"Cannot read config: {e}"}
                    cfg = None
                if cfg:
                    results = []
                    for pname in sorted((cfg.get("profiles") or {}).keys()):
                        creds = _resolve_credentials(profile=pname)
                        if creds:
                            r = await _test_profile(tv, pname, creds)
                            results.append(r)
                        else:
                            results.append({"profile": pname, "status": "skipped", "reason": "No credentials resolved"})
                    result = {"results": results}
            elif name == "logout":
                result = await tv.logout()
            elif name == "dismiss_ad":
                result = await tv.dismiss_ad()
            elif name == "replay_autoplay":
                result = await tv.replay_autoplay(speed=arguments.get("speed", 0))
            else:
                raise ValueError(f"Unknown tool: {name}")

            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except Exception as e:
            return [TextContent(type="text", text=json.dumps({"error": str(e)}, indent=2))]


async def _run():
    async with mcp.server.stdio.stdio_server() as (read, write):
        await server.run(
            read, write, InitializationOptions(
                server_name="pytvtools",
                server_version="0.1.0",
                capabilities={"tools": {}},
            )
        )


def main():
    asyncio.run(_run())


if __name__ == "__main__":
    main()
