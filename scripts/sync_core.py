"""Sync pytvtools_core to a standalone public repo.

Usage:
    python scripts/sync_core.py ../pytvtools-core-public
    python scripts/sync_core.py ../pytvtools-core-public --commit "feat: update indicators"
"""

from __future__ import annotations

import subprocess
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CORE_SRC = REPO_ROOT / "src" / "pytvtools_core"
CORE_PYPROJECT = CORE_SRC / "pyproject.toml"

CORE_TESTS = [
    REPO_ROOT / "tests" / "test_indicators.py",
    REPO_ROOT / "tests" / "test_watchlists.py",
    REPO_ROOT / "tests" / "test_tvdata.py",
]

CORE_NOTEBOOKS = [
    REPO_ROOT / "notebooks" / "cache_refresh.py",
    REPO_ROOT / "notebooks" / "stress_test_tvdata_limits.py",
]

CORE_JOBS = [
    REPO_ROOT / "jobs" / "cache_refresh_on_demand.json",
    REPO_ROOT / "jobs" / "cache_refresh_daily.json",
    REPO_ROOT / "jobs" / "cache_refresh_weekly.json",
    REPO_ROOT / "jobs" / "cache_refresh_monthly.json",
]


def main() -> None:
    args = sys.argv[1:]
    commit_msg = None
    if "--commit" in args:
        idx = args.index("--commit")
        commit_msg = args[idx + 1]
        args = args[:idx] + args[idx + 2:]

    target = Path(args[0]) if args else REPO_ROOT.parent / "pytvtools-core-public"
    target = target.resolve()

    # Copy source
    target_src = target / "src" / "pytvtools_core"
    if target_src.exists():
        shutil.rmtree(target_src)
    shutil.copytree(CORE_SRC, target_src)
    print(f"Copied src/ to {target_src}")

    # Copy tests
    target_tests = target / "tests"
    target_tests.mkdir(parents=True, exist_ok=True)
    for t in CORE_TESTS:
        if t.exists():
            shutil.copy2(t, target_tests / t.name)
            print(f"Copied {t.name}")

    # Copy notebooks
    target_notebooks = target / "notebooks"
    target_notebooks.mkdir(parents=True, exist_ok=True)
    for n in CORE_NOTEBOOKS:
        if n.exists():
            shutil.copy2(n, target_notebooks / n.name)
            print(f"Copied {n.name}")

    # Copy jobs
    target_jobs = target / "jobs"
    target_jobs.mkdir(parents=True, exist_ok=True)
    for j in CORE_JOBS:
        if j.exists():
            shutil.copy2(j, target_jobs / j.name)
            print(f"Copied {j.name}")

    # Generate pyproject.toml in target root
    core_pp = target / "pyproject.toml"
    core_pp.write_text(f"""[project]
name = "pytvtools-core"
version = "0.1.0"
description = "Pure Python TradingView tools - indicators, watchlists, TVData WebSocket fetcher."
requires-python = ">=3.11"
dependencies = ["websockets>=16.0"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
""", encoding="utf-8")
    print(f"Generated {core_pp}")

    # Initialize git repo if needed
    if not (target / ".git").exists():
        subprocess.run(["git", "-C", str(target), "init"], check=True)
        subprocess.run(["git", "-C", str(target), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(target), "commit", "-m", "Initial sync"], check=True)
        print(f"Initialised git repo at {target}")
    elif commit_msg:
        subprocess.run(["git", "-C", str(target), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(target), "commit", "-m", commit_msg],
            check=True,
        )
        print(f"Committed: {commit_msg}")

    print(f"\nDone. Sync target: {target}")


if __name__ == "__main__":
    main()
