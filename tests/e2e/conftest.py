"""E2E test configuration and skip guards.

E2E tests are OFF by default. Enable with:
    CLAWWRAP_E2E=1 pytest tests/e2e/ -v -s

They require:
- wacli authenticated (run 'wacli auth' if needed)
- WhatsApp account active and not recently rate-limited
- Rate limit lockfile permits a send (max 3/day, min 60s interval)
"""
from __future__ import annotations

import os

import pytest


def e2e_enabled() -> bool:
    return os.environ.get("CLAWWRAP_E2E", "").strip() == "1"


skip_unless_e2e = pytest.mark.skipif(
    not e2e_enabled(),
    reason="E2E tests disabled. Set CLAWWRAP_E2E=1 to run live WhatsApp tests.",
)
