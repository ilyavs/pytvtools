"""Shared fixtures for pytvtools tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_ws():
    """A mock WebSocket connection that echoes back CDP responses."""
    ws = AsyncMock()
    ws.send = AsyncMock()
    ws.recv = AsyncMock()
    return ws


@pytest.fixture
def mock_http_client():
    """A mock httpx.AsyncClient."""
    client = MagicMock()
    client.get = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client
