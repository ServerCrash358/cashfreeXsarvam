"""Integration suites call the real Cashfree SANDBOX. Never run in CI; skipped unless RUN_INTEGRATION=1.
Run deliberately and record each result in docs/INTEGRATION_TESTS.md (Status column):

  $env:RUN_INTEGRATION=1; python -m pytest tests/integration -v -rs        # PowerShell
  RUN_INTEGRATION=1 python -m pytest tests/integration -v -rs              # bash
"""
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: calls the Cashfree sandbox (needs RUN_INTEGRATION=1)")
    config.addinivalue_line("markers", "slow: takes 25 s or more")


def pytest_collection_modifyitems(config, items):
    if os.getenv("RUN_INTEGRATION") == "1":
        return
    skip = pytest.mark.skip(reason="integration: set RUN_INTEGRATION=1 to call the Cashfree sandbox")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)
