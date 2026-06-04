"""
Chrome lifecycle management — launch, health-check, restart a headless Chrome
with CDP enabled. Cross-platform (Windows, macOS, Linux/ARM).
"""
from __future__ import annotations

import asyncio
import logging
import os
import platform
import shutil
from pathlib import Path
from typing import Any

import httpx

from pytvtools.cdp import wait_for_cdp

logger = logging.getLogger(__name__)

CDP_PORT = int(os.environ.get("TV_CDP_PORT", "9222"))
TV_URL = os.environ.get("TV_URL", "https://www.tradingview.com/chart/")
USER_DATA_DIR = os.environ.get(
    "TV_USER_DATA_DIR",
    str(Path.home() / ".pytvtools-profile"),
)


def _find_chrome() -> str | None:
    system = platform.system()
    if system == "Windows":
        candidates = [
            os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
    elif system == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ]
    else:
        candidates = [
            "google-chrome",
            "google-chrome-stable",
            "chromium-browser",
            "chromium",
        ]
    for c in candidates:
        path = shutil.which(c) or c
        if os.path.isfile(path) or shutil.which(c):
            return path
    return None


class Chrome:
    """Manages a headless Chrome process for TradingView."""

    def __init__(
        self,
        port: int = CDP_PORT,
        tv_url: str = TV_URL,
        user_data_dir: str | Path = USER_DATA_DIR,
        binary: str | None = None,
    ):
        self.port = port
        self.tv_url = tv_url
        self.user_data_dir = Path(user_data_dir)
        self._binary = binary or _find_chrome()
        self._proc: asyncio.subprocess.Process | None = None

    async def start(self, headless: bool = True) -> None:
        if not self._binary:
            raise RuntimeError(
                "Chrome not found. Install Chrome/Chromium or set TV_CHROME_BINARY."
            )
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        args = [
            self._binary,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
            "--no-sandbox",
            "--disable-gpu",
            self.tv_url,
        ]
        if headless:
            args.insert(-1, "--headless=new")

        self._proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        ok = await wait_for_cdp(port=self.port, timeout=30)
        if not ok:
            raise RuntimeError("Chrome started but CDP never responded")

    async def stop(self) -> None:
        if self._proc:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                self._proc.kill()
                await self._proc.wait()
            self._proc = None

    async def restart(self, headless: bool = True) -> None:
        await self.stop()
        await asyncio.sleep(1)
        await self.start(headless=headless)

    @staticmethod
    def launch_command(
        port: int = CDP_PORT,
        tv_url: str = TV_URL,
        user_data_dir: str | Path = USER_DATA_DIR,
        headless: bool = True,
    ) -> str:
        """Print the shell command to launch Chrome on any platform.

        Works in both Linux bash and Windows PowerShell.
        """
        binary = _find_chrome() or "google-chrome"
        ud = str(user_data_dir)
        hl = "--headless=new" if headless else ""
        return (
            f"{binary} --remote-debugging-port={port}"
            f" --user-data-dir={ud}"
            f" --no-first-run --no-default-browser-check --disable-sync"
            f" --no-sandbox --disable-gpu"
            f" {hl}"
            f" \"{tv_url}\""
        )

    async def is_alive(self) -> bool:
        if not self._proc or self._proc.returncode is not None:
            return False
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"http://localhost:{self.port}/json/version", timeout=3
                )
                return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False
