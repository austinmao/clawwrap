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


class TestForChannel:
    """T006-T009 — per-channel classmethod configuration (spec 085 US1)."""

    def test_from_channel_config_whatsapp(self) -> None:
        """T006: full org_config for whatsapp wires through untouched."""
        cfg = {
            "rate_limits": {
                "channels": {
                    "whatsapp": {
                        "max_per_day": 3,
                        "min_interval_seconds": 60,
                        "jitter": {"min": 10, "max": 15},
                    }
                }
            }
        }
        guard = RateLimitGuard.for_channel("whatsapp", cfg)
        assert guard._max_per_day == 3
        assert guard._min_interval == 60
        assert guard._jitter_min == 10.0
        assert guard._jitter_max == 15.0
        assert guard._lockfile.name == "ratelimit-whatsapp.json"

    def test_from_channel_config_bluebubbles_defaults(self) -> None:
        """T007: bluebubbles with empty config falls back to _CHANNEL_DEFAULTS."""
        guard = RateLimitGuard.for_channel("bluebubbles", {})
        assert guard._max_per_day == 20
        assert guard._min_interval == 30
        assert guard._jitter_min == 3.0
        assert guard._jitter_max == 5.0
        assert guard._lockfile.name == "ratelimit-bluebubbles.json"

    def test_per_channel_lockfile_isolation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """T008: exceeding the bluebubbles daily quota must not block whatsapp."""
        # Redirect ~/.clawwrap to an isolated tmp dir for this test.
        fake_home = tmp_path
        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        bb_guard = RateLimitGuard.for_channel("bluebubbles", {})
        bb_lock = bb_guard._lockfile
        bb_lock.parent.mkdir(parents=True, exist_ok=True)
        # Pretend bluebubbles has hit its 20/day cap.
        bb_lock.write_text(
            json.dumps({
                "last_send_ts": time.time() - 300,
                "count_today": 20,
                "date": _today(),
            })
        )

        # Bluebubbles is exhausted.
        with pytest.raises(RateLimitError, match="daily limit"):
            bb_guard.check_and_record(dry_run=False)

        # WhatsApp has its own lockfile and should be unaffected.
        wa_guard = RateLimitGuard.for_channel("whatsapp", {})
        assert wa_guard._lockfile != bb_guard._lockfile
        result = wa_guard.check_and_record(dry_run=True)
        assert result.allowed is True

    def test_missing_org_config_uses_defaults(self) -> None:
        """T009: imessage → bluebubbles alias; same lockfile, same defaults."""
        guard = RateLimitGuard.for_channel("imessage", {})
        assert guard._lockfile.name == "ratelimit-bluebubbles.json"
        assert guard._max_per_day == 20
        assert guard._min_interval == 30
        # jitter also follows the bluebubbles defaults
        assert guard._jitter_min == 3.0
        assert guard._jitter_max == 5.0
