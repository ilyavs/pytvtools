"""Fetch Pine Script source code of a public indicator.

Usage:
    docker exec -w /app docker-pytvtools-1 python examples/get_pine_source.py
"""

import asyncio
import logging

from pytvtools import TV, wait_for_cdp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


async def main() -> None:
    await wait_for_cdp()

    async with TV() as tv:
        # Search for a community indicator
        results = await tv.search_indicators("Two-PR Moving Averages")
        if not results:
            print("Indicator not found")
            return

        study_id = results[0]["study_id"]
        name = results[0]["name"]
        print(f"Found: {name}  ({study_id})")

        # Fetch the Pine Script source
        source = await tv.get_pine_source(study_id)
        if source:
            lines = source.splitlines()
            print(f"Source fetched ({len(lines)} lines):")
            for line in lines[:20]:
                print(f"  {line}")
            if len(lines) > 20:
                print(f"  ... ({len(lines) - 20} more lines)")
        else:
            print("No source available (built-in indicator or fetch failed)")


if __name__ == "__main__":
    asyncio.run(main())
