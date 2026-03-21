"""Unit tests for the WhatsApp rate limit guard."""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import pytest

from clawwrap.engine.rate_limit import RateLimitError, RateLimitGuard


def _today() -> str:
    return date.today().isoformat()


class TestRateLimitGuard:
    def test_first_send_is_allowed(self, tmp_path: Path) -> None:
        guard = RateLimitGuard(lockfile=tmp_path / "wa-ratelimit.json", max_per_day=3)
        result = guard.check_and_record(dry_run=True)
        assert result.allowed is True
        assert result.jitter_seconds >= 10.0

    def test_second_send_within_min_interval_is_blocked(self, tmp_path: Path) -> None:
        lockfile = tmp_path / "wa-ratelimit.json"
        guard = RateLimitGuard(lockfile=lockfile, max_per_day=3, min_interval_seconds=60)
        # Record a send 5 seconds ago
        now = time.time()
        lockfile.write_text(
            json.dumps({"last_send_ts": now - 5, "count_today": 1, "date": _today()})
        )
        with pytest.raises(RateLimitError, match="too soon"):
            guard.check_and_record(dry_run=False)

    def test_daily_limit_exceeded_is_blocked(self, tmp_path: Path) -> None:
        lockfile = tmp_path / "wa-ratelimit.json"
        guard = RateLimitGuard(lockfile=lockfile, max_per_day=3)
        lockfile.write_text(
            json.dumps({"last_send_ts": time.time() - 300, "count_today": 3, "date": _today()})
        )
        with pytest.raises(RateLimitError, match="daily limit"):
            guard.check_and_record(dry_run=False)

    def test_daily_count_resets_on_new_day(self, tmp_path: Path) -> None:
        lockfile = tmp_path / "wa-ratelimit.json"
        guard = RateLimitGuard(lockfile=lockfile, max_per_day=3)
        lockfile.write_text(
            json.dumps({"last_send_ts": time.time() - 90000, "count_today": 3, "date": "2020-01-01"})
        )
        result = guard.check_and_record(dry_run=True)
        assert result.allowed is True

    def test_lockfile_is_written_on_record(self, tmp_path: Path) -> None:
        lockfile = tmp_path / "wa-ratelimit.json"
        guard = RateLimitGuard(lockfile=lockfile, max_per_day=3)
        guard.check_and_record(dry_run=False)
        data = json.loads(lockfile.read_text())
        assert data["count_today"] == 1
        assert "last_send_ts" in data
