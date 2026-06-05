"""Tests for chrome.py — Chrome lifecycle and cross-platform launch."""

from __future__ import annotations

import platform
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pytvtools.chrome import Chrome, _find_chrome


class TestFindChrome:
    """_find_chrome resolves Chrome binary per platform."""

    @patch("pytvtools.chrome.platform.system", return_value="Windows")
    @patch("pytvtools.chrome.shutil.which", return_value=None)
    @patch("pytvtools.chrome.os.path.isfile", return_value=True)
    @patch("pytvtools.chrome.os.path.expandvars", side_effect=lambda x: x)
    def test_windows_finds_chrome(self, mock_expandvars, mock_isfile, mock_which, mock_system):
        path = _find_chrome()
        assert path is not None
        assert "chrome.exe" in path

    @patch("pytvtools.chrome.platform.system", return_value="Windows")
    @patch("pytvtools.chrome.shutil.which", return_value=None)
    @patch("pytvtools.chrome.os.path.isfile", return_value=False)
    @patch("pytvtools.chrome.os.path.expandvars", side_effect=lambda x: x)
    def test_windows_not_found(self, mock_expandvars, mock_isfile, mock_which, mock_system):
        path = _find_chrome()
        assert path is None

    @patch("pytvtools.chrome.platform.system", return_value="Darwin")
    @patch("pytvtools.chrome.shutil.which", return_value=None)
    @patch("pytvtools.chrome.os.path.isfile", return_value=True)
    def test_macos_finds_chrome(self, mock_isfile, mock_which, mock_system):
        path = _find_chrome()
        assert path is not None
        assert "Google Chrome" in path

    @patch("pytvtools.chrome.platform.system", return_value="Linux")
    @patch("pytvtools.chrome.shutil.which", side_effect=lambda x: x if x == "google-chrome" else None)
    def test_linux_finds_chrome(self, mock_which, mock_system):
        path = _find_chrome()
        assert path == "google-chrome"

    @patch("pytvtools.chrome.platform.system", return_value="Linux")
    @patch("pytvtools.chrome.shutil.which", return_value=None)
    def test_linux_not_found(self, mock_which, mock_system):
        path = _find_chrome()
        assert path is None

    @patch("pytvtools.chrome.platform.system", return_value="Linux")
    @patch("pytvtools.chrome.shutil.which", side_effect=lambda x: "chromium-browser" if x == "chromium-browser" else None)
    def test_linux_finds_chromium(self, mock_which, mock_system):
        path = _find_chrome()
        assert path == "chromium-browser"


class TestChrome:
    """Chrome manages a headless Chrome subprocess."""

    @patch("pytvtools.chrome.wait_for_cdp", AsyncMock(return_value=True))
    @patch("pytvtools.chrome._find_chrome", return_value="/usr/bin/google-chrome")
    @patch("pytvtools.chrome.asyncio.create_subprocess_exec", AsyncMock())
    async def test_start_headless(self, mock_find):
        chrome = Chrome(binary="/usr/bin/google-chrome")
        await chrome.start(headless=True)
        assert chrome._proc is not None

    @patch("pytvtools.chrome.wait_for_cdp", AsyncMock(return_value=True))
    @patch("pytvtools.chrome._find_chrome", return_value="/usr/bin/google-chrome")
    @patch("pytvtools.chrome.asyncio.create_subprocess_exec", AsyncMock())
    async def test_start_without_headless_flag(self, mock_find):
        chrome = Chrome(binary="/usr/bin/google-chrome")
        await chrome.start(headless=False)
        assert chrome._proc is not None

    @patch("pytvtools.chrome._find_chrome", return_value=None)
    async def test_start_raises_no_binary(self, mock_find):
        chrome = Chrome(binary=None)
        with pytest.raises(RuntimeError, match="Chrome not found"):
            await chrome.start()

    @patch("pytvtools.chrome.wait_for_cdp", AsyncMock(return_value=False))
    @patch("pytvtools.chrome._find_chrome", return_value="/usr/bin/google-chrome")
    @patch("pytvtools.chrome.asyncio.create_subprocess_exec", AsyncMock())
    async def test_start_raises_cdp_timeout(self, mock_find):
        chrome = Chrome(binary="/usr/bin/google-chrome")
        with pytest.raises(RuntimeError, match="CDP never responded"):
            await chrome.start()

    @patch("pytvtools.chrome.wait_for_cdp", AsyncMock(return_value=True))
    @patch("pytvtools.chrome._find_chrome", return_value="/usr/bin/google-chrome")
    @patch("pytvtools.chrome.asyncio.create_subprocess_exec", AsyncMock())
    async def test_stop(self, mock_find):
        chrome = Chrome(binary="/usr/bin/google-chrome")
        await chrome.start()
        await chrome.stop()
        assert chrome._proc is None

    @patch("pytvtools.chrome.wait_for_cdp", AsyncMock(return_value=True))
    @patch("pytvtools.chrome._find_chrome", return_value="/usr/bin/google-chrome")
    @patch("pytvtools.chrome.asyncio.create_subprocess_exec", AsyncMock())
    async def test_stop_called_before_start(self, mock_find):
        chrome = Chrome()
        await chrome.stop()  # should not raise

    @patch("pytvtools.chrome.wait_for_cdp", AsyncMock(return_value=True))
    @patch("pytvtools.chrome._find_chrome", return_value="/usr/bin/google-chrome")
    @patch("pytvtools.chrome.asyncio.create_subprocess_exec", AsyncMock())
    async def test_restart(self, mock_find):
        chrome = Chrome(binary="/usr/bin/google-chrome")
        await chrome.start()
        await chrome.restart(headless=True)
        assert chrome._proc is not None

    @patch("pytvtools.chrome.wait_for_cdp", AsyncMock(return_value=False))
    @patch("pytvtools.chrome._find_chrome", return_value="/usr/bin/google-chrome")
    @patch("pytvtools.chrome.asyncio.create_subprocess_exec", AsyncMock())
    async def test_restart_fails_if_cdp_no_response(self, mock_find):
        chrome = Chrome(binary="/usr/bin/google-chrome")
        with pytest.raises(RuntimeError):
            await chrome.restart(headless=True)

    @patch("pytvtools.chrome.httpx.AsyncClient")
    @patch("pytvtools.chrome.wait_for_cdp", AsyncMock(return_value=True))
    @patch("pytvtools.chrome._find_chrome", return_value="/usr/bin/google-chrome")
    @patch("pytvtools.chrome.asyncio.create_subprocess_exec")
    async def test_is_alive_checks_cdp_version(self, mock_subprocess, mock_find, mock_http_client):
        mock_proc = AsyncMock()
        mock_proc.returncode = None
        mock_subprocess.return_value = mock_proc

        mock_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_instance.get = AsyncMock(return_value=mock_response)
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=None)
        mock_http_client.return_value = mock_instance

        chrome = Chrome(binary="/usr/bin/google-chrome")
        await chrome.start()
        alive = await chrome.is_alive()
        assert alive is True

    @patch("pytvtools.chrome.httpx.AsyncClient")
    @patch("pytvtools.chrome.wait_for_cdp", AsyncMock(return_value=True))
    @patch("pytvtools.chrome._find_chrome", return_value="/usr/bin/google-chrome")
    @patch("pytvtools.chrome.asyncio.create_subprocess_exec", AsyncMock())
    async def test_is_alive_returns_false_if_no_proc(self, mock_http_client, mock_find):
        chrome = Chrome()
        alive = await chrome.is_alive()
        assert alive is False


class TestLaunchCommand:
    """Chrome.launch_command() returns a cross-platform CLI string."""

    @patch("pytvtools.chrome._find_chrome", return_value="/usr/bin/google-chrome")
    def test_defaults(self, mock_find):
        cmd = Chrome.launch_command()
        assert "google-chrome" in cmd
        assert "--remote-debugging-port=9222" in cmd
        assert "--headless=new" in cmd
        assert "https://www.tradingview.com/chart/" in cmd

    @patch("pytvtools.chrome._find_chrome", return_value="/usr/bin/google-chrome")
    def test_custom_port(self, mock_find):
        cmd = Chrome.launch_command(port=9223)
        assert "--remote-debugging-port=9223" in cmd

    @patch("pytvtools.chrome._find_chrome", return_value="/usr/bin/google-chrome")
    def test_not_headless(self, mock_find):
        cmd = Chrome.launch_command(headless=False)
        assert "--headless=new" not in cmd

    @patch("pytvtools.chrome._find_chrome", return_value="/usr/bin/google-chrome")
    def test_custom_url(self, mock_find):
        cmd = Chrome.launch_command(tv_url="https://example.com")
        assert "example.com" in cmd

    @patch("pytvtools.chrome._find_chrome", return_value="/usr/bin/google-chrome")
    def test_custom_user_data_dir(self, mock_find):
        cmd = Chrome.launch_command(user_data_dir="/tmp/my-profile")
        assert "/tmp/my-profile" in cmd

    @patch("pytvtools.chrome._find_chrome", return_value=None)
    def test_fallback_binary(self, mock_find):
        cmd = Chrome.launch_command()
        assert "google-chrome" in cmd


class TestChromeLifecycle:
    """Integration-style tests for Chrome lifecycle edge cases."""

    @patch("pytvtools.chrome.wait_for_cdp", AsyncMock(return_value=True))
    @patch("pytvtools.chrome._find_chrome", return_value="/usr/bin/google-chrome")
    @patch("pytvtools.chrome.asyncio.create_subprocess_exec", AsyncMock())
    async def test_create_user_data_dir(self, mock_find):
        chrome = Chrome(binary="/usr/bin/google-chrome")
        await chrome.start()
        assert chrome.user_data_dir.exists()
