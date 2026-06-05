"""Integration tests: run each example script against a live TradingView tab.

Requires a running Chrome with CDP on port 9222 and a TV chart tab open.
Skip with:  pytest -m "not integration"
Run with:   pytest -m integration
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLES = sorted(Path(__file__).resolve().parents[1].glob("examples/*.py"))


@pytest.mark.integration
@pytest.mark.parametrize("script", EXAMPLES, ids=lambda p: p.stem)
def test_example_runs_successfully(script: Path):
    """Each example script must exit with code 0."""
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        msg = (
            f"{script.name} failed (exit {result.returncode})\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
        raise AssertionError(msg)
