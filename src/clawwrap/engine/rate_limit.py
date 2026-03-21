"""WhatsApp rate limit guard for clawwrap E2E send operations.

Enforces safe sending behaviour to avoid WhatsApp anti-bot bans:
- Minimum 60-second interval between sends (to same or any recipient)
- Daily send limit (default 3 for initial testing warmup)
- Randomised 10-15 second pre-send jitter to appear human
- Persistent lockfile tracks state across process restarts

Research basis (2026-03-14):
  - WhatsApp unofficial clients: no documented limit but ban risk is very high
  - Conservative human-like pattern: 10-15s jitter, <=3 test sends/day, no bursts
  - Official Business API pair rate: 1 msg/6s; we use 60s minimum for safety margin
"""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path


class RateLimitError(Exception):
    """Raised when a send would violate the WhatsApp rate limit policy."""


@dataclass
class CheckResult:
    allowed: bool
    jitter_seconds: float
    reason: str


class RateLimitGuard:
    """Guards outbound wacli send calls against WhatsApp rate limits.

    Args:
        lockfile: Path to the JSON lockfile tracking send history.
            Defaults to ~/.clawwrap/wa-ratelimit.json.
        max_per_day: Maximum sends allowed per calendar day.
        min_interval_seconds: Minimum gap between any two sends (seconds).
        jitter_min: Minimum pre-send human delay (seconds).
        jitter_max: Maximum pre-send human delay (seconds).
    """

    def __init__(
        self,
        lockfile: Path | None = None,
        max_per_day: int = 3,
        min_interval_seconds: float = 60.0,
        jitter_min: float = 10.0,
        jitter_max: float = 15.0,
    ) -> None:
        self._lockfile = lockfile or Path.home() / ".clawwrap" / "wa-ratelimit.json"
        self._max_per_day = max_per_day
        self._min_interval = min_interval_seconds
        self._jitter_min = jitter_min
        self._jitter_max = jitter_max

    def check_and_record(self, *, dry_run: bool = False) -> CheckResult:
        """Check rate limits and optionally record the send.

        Args:
            dry_run: When True, validate limits but do NOT write the lockfile.

        Returns:
            CheckResult with allowed=True and the jitter delay to apply.

        Raises:
            RateLimitError: If any limit would be exceeded.
        """
        state = self._load()
        today = date.today().isoformat()
        now = time.time()

        # Reset daily counter on new day
        count_today = state.get("count_today", 0) if state.get("date") == today else 0
        last_send_ts: float = float(state.get("last_send_ts", 0.0))

        # Check daily limit
        if count_today >= self._max_per_day:
            raise RateLimitError(
                f"daily limit of {self._max_per_day} test sends reached. "
                "Reset tomorrow or increase max_per_day for warmup-complete accounts."
            )

        # Check minimum interval
        elapsed = now - last_send_ts
        if last_send_ts > 0 and elapsed < self._min_interval:
            wait_remaining = self._min_interval - elapsed
            raise RateLimitError(
                f"too soon: last send was {elapsed:.0f}s ago; "
                f"minimum interval is {self._min_interval:.0f}s. "
                f"Wait {wait_remaining:.0f}s more."
            )

        jitter = random.uniform(self._jitter_min, self._jitter_max)  # noqa: S311

        if not dry_run:
            self._lockfile.parent.mkdir(parents=True, exist_ok=True)
            self._lockfile.write_text(
                json.dumps({
                    "last_send_ts": now,
                    "count_today": count_today + 1,
                    "date": today,
                }),
                encoding="utf-8",
            )

        return CheckResult(allowed=True, jitter_seconds=jitter, reason="ok")

    def _load(self) -> dict[str, object]:
        if not self._lockfile.exists():
            return {}
        try:
            data = json.loads(self._lockfile.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}
