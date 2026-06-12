"""Inspect indicator data structures."""
import asyncio
import json
import sys
sys.path.insert(0, ".")

from pytvtools import TV, wait_for_cdp
from pytvtools.tv import _js_str


async def inspect(tv, eid, name):
    raw = await tv._eval(f"""
    (function() {{
        var model = window.TradingViewApi.chart().chartWidget().model();
        var ds = model.dataSourceForId({_js_str(eid)});
        if (!ds) return {{error: 'no ds'}};
        var info = {{}};
        info.title = ds.title ? ds.title() : 'no title';
        info.simplePlotsCount = ds._simplePlotsCount;

        var items = ds._data && ds._data._items;
        if (items && items.length > 0) {{
            info.itemCount = items.length;
            var samples = [];
            for (var i = Math.max(0, items.length - 3); i < items.length; i++) {{
                samples.push(JSON.parse(JSON.stringify(items[i])));
            }}
            info.samples = samples;
            info.lastValue = JSON.parse(JSON.stringify(items[items.length - 1].value));
        }}

        var mv = ds._metaInfo && ds._metaInfo._value;
        if (mv) {{
            if (mv.plots) {{
                info.plotMapping = {{}};
                for (var pk in mv.plots) {{
                    info.plotMapping[pk] = mv.plots[pk].id;
                }}
            }}
            if (mv.styles) {{
                info.styleTitles = {{}};
                for (var sk in mv.styles) {{
                    info.styleTitles[sk] = mv.styles[sk].title || sk;
                }}
            }}
        }}
        return info;
    }})()
    """)
    print(f"\n=== {name} (id={eid}) ===")
    print(json.dumps(raw, indent=2, default=str))


async def main():
    await wait_for_cdp(timeout=10)
    async with TV(port=9222) as tv:
        await tv.remove_all_indicators()

        # Test BB
        eid = await tv.add_indicator("BB@tv-basicstudies")
        await asyncio.sleep(2)
        await inspect(tv, eid, "Bollinger Bands")

        # Test RSI
        eid2 = await tv.add_indicator("RSI@tv-basicstudies")
        await asyncio.sleep(2)
        await inspect(tv, eid2, "RSI")

        # Test MACD
        eid3 = await tv.add_indicator("MACD@tv-basicstudies")
        await asyncio.sleep(2)
        await inspect(tv, eid3, "MACD")


asyncio.run(main())
