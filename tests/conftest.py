"""Shared fixtures for the monitor-core (breeding_core.py) test suite.

Every test in this package is SANDBOX-ONLY: the real project directories
under ``~/.hermes/breeding/<project>/`` are read-only inputs at most, and
every write goes to a pytest ``tmp_path``. No Discord, Drive, network, or
git-push side effect is ever performed here.
"""

import json
import sys
from pathlib import Path

import pytest

MONITOR_CORE_DIR = Path(__file__).resolve().parents[1]
BREEDING_ROOT = MONITOR_CORE_DIR.parents[1]
REAL_TRACKERS = sorted(BREEDING_ROOT.glob("*/tracker.json"))

if str(MONITOR_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(MONITOR_CORE_DIR))


@pytest.fixture
def lantz_tracker():
    """The real Lantz tracker.json, loaded read-only as an in-memory dict.

    Real breeding data, not a synthetic fixture: unicode, smart quotes,
    multi-paragraph observation logs and a null-heavy field set that a
    synthetic dict would flatter.
    """
    path = BREEDING_ROOT / "lantz" / "tracker.json"
    if not path.exists():
        pytest.skip("real lantz tracker.json not present")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def sandbox_project(tmp_path):
    """An empty sandbox project directory standing in for a real one."""
    project = tmp_path / "sandbox-cross"
    project.mkdir()
    return project
