import asyncio
import logging
from pytvtools import TV

logging.basicConfig(level=logging.INFO)

async def main():
    async with TV() as tv:
        await tv.set_symbol("BINANCE:BTCUSDT")
        await tv.set_timeframe("1D")
        
        await tv.get_ohlcv(summary=False)
        eid = await tv.add_indicator("STD;Money_Flow")
        await asyncio.sleep(3)

        # Read study inputs/metadata
        info = await tv._eval(f'''
        (function() {{
            var ds = window.TradingViewApi.chart().chartWidget().model()
                .dataSourceForId({eid!r});
            if (!ds) return "no ds";
            var info = {{}};
            info.title = ds.title();
            try {{
                var inputs = ds.getInputsInfo();
                info.inputs = inputs.map(function(i) {{ 
                    return {{id: i.id, name: i.name, value: i.value, type: i.type}};
                }});
            }} catch(e) {{ info.inputsError = e.message; }}
            
            try {{
                var vals = ds.getInputValues();
                info.inputValues = JSON.parse(JSON.stringify(vals));
            }} catch(e) {{ info.inputValuesError = e.message; }}

            try {{
                info.styleInfo = JSON.parse(JSON.stringify(ds.getStyleInfo()));
            }} catch(e) {{ info.styleInfoError = e.message; }}
            
            return JSON.stringify(info);
        }})()
        ''')
        print("Study info:")
        print(info)

asyncio.run(main())
