"""Minimal CDP test — just connect and eval."""
import asyncio
import logging
logging.basicConfig(level=logging.DEBUG)

from pytvtools.cdp import CdpConnection, find_tv_target, make_ws_url


async def main():
    target = await find_tv_target()
    if not target:
        print("No TV target found")
        return
    ws_url = make_ws_url(target)
    print(f"Target: {target['id']}  WS: {ws_url}")
    
    cdp = CdpConnection(ws_url)
    try:
        await asyncio.wait_for(cdp.connect(), timeout=10)
        print("Connected!")
        
        val = await asyncio.wait_for(
            cdp.evaluate("document.title"),
            timeout=5,
        )
        print(f"Document title: {val}")
    except asyncio.TimeoutError:
        print("TIMEOUT")
    except Exception as e:
        print(f"ERROR: {e}")
    finally:
        await cdp.close()


if __name__ == "__main__":
    asyncio.run(main())
