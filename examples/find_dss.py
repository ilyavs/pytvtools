"""Find DSS by hpotter and fetch its source code."""
import asyncio
import logging

from pytvtools import TV, wait_for_cdp

logging.basicConfig(level=logging.INFO)

async def main():
    await wait_for_cdp()
    async with TV() as tv:
        results = await tv.search_indicators("DSS")
        for r in results:
            pub = r.get("publisher", "")
            name = r.get("name", "")
            print(f"  {r['id']:30s}  {name:40s}  {pub}")
        if not results:
            print("No results found")

asyncio.run(main())
