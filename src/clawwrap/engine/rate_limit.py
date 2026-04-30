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

import functools
import json
import random
import time
import warnings
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

# Per-channel rate-limit defaults used when ``org_config`` omits a channel.
#
# WhatsApp values are deliberately conservative to stay under Meta's anti-bot
# heuristics (see docstring above). BlueBubbles/iMessage is a native-app
# transport with no server-side throttling, so the defaults are tighter only
# to avoid the Messages.app UI queue backing up during bulk sends.
#
# ``imessage`` is an alias — it shares the bluebubbles config AND the same
# lockfile path, so a single daily quota covers both channel names.
_CHANNEL_DEFAULTS: dict[str, dict[str, Any]] = {
    "whatsapp": {
        "max_per_day": 3,
        "min_interval_seconds": 60.0,
        "jitter_min": 10.0,
        "jitter_max": 15.0,
        "lockfile_channel": "whatsapp",
    },
    "bluebubbles": {
        "max_per_day": 20,
        "min_interval_seconds": 30.0,
        "jitter_min": 3.0,
        "jitter_max": 5.0,
        "lockfile_channel": "bluebubbles",
    },
    "imessage": {
        "max_per_day": 20,
        "min_interval_seconds": 30.0,
        "jitter_min": 3.0,
        "jitter_max": 5.0,
        "lockfile_channel": "bluebubbles",  # alias — shares bluebubbles lockfile
    },
}


class RateLimitError(Exception):
    """Raised when a send would violate the WhatsApp rate limit policy."""


class EscapeHatchError(RuntimeError):
    """Raised when a channel handler is invoked outside of outbound.submit context.

    Direct channel calls bypass the clawwrap gate's resolve → verify → dispatch →
    audit pipeline. Handlers must be entered via ``outbound.submit``, which sets
    ``_gate_context.active = True`` before dispatch. For break-glass scenarios,
    set ``CLAWWRAP_EMERGENCY=1`` in the environment — direct calls then proceed
    with a WARN audit entry instead of raising.
    """

    _DEFAULT_MESSAGE = (
        "Direct channel call outside outbound.submit context. "
        "Use clawwrap outbound.submit --channel <ch>. "
        "For emergencies set CLAWWRAP_EMERGENCY=1."
    )

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self._DEFAULT_MESSAGE)


@dataclass
class CheckResult:
    allowed: bool
    jitter_seconds: float
    reason: str


@functools.lru_cache(maxsize=1)
def _emit_direct_constructor_deprecation() -> None:
    """Emit a single DeprecationWarning per process when the direct
    ``RateLimitGuard(...)`` constructor is used instead of
    ``RateLimitGuard.for_channel(...)``.

    ``functools.lru_cache`` with ``maxsize=1`` guarantees the body runs once
    per process: subsequent calls return the cached ``None`` without re-firing.
    """
    warnings.warn(
        "RateLimitGuard direct constructor is deprecated — use "
        "RateLimitGuard.for_channel(channel, org_config) for per-channel "
        "configuration. The direct constructor will be removed in a future "
        "clawwrap release.",
        DeprecationWarning,
        stacklevel=3,
    )


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
        _from_classmethod: bool = False,
    ) -> None:
        if not _from_classmethod:
            _emit_direct_constructor_deprecation()
        self._lockfile = lockfile or Path.home() / ".clawwrap" / "wa-ratelimit.json"
        self._max_per_day = max_per_day
        self._min_interval = min_interval_seconds
        self._jitter_min = jitter_min
        self._jitter_max = jitter_max

    @classmethod
    def for_channel(
        cls,
        channel: str,
        org_config: dict[str, Any],
    ) -> RateLimitGuard:
        """Construct a channel-scoped RateLimitGuard.

        Loads ``org_config["rate_limits"]["channels"][channel]`` if present and
        falls back to the per-channel defaults in ``_CHANNEL_DEFAULTS``. The
        lockfile path is ``~/.clawwrap/ratelimit-{lockfile_channel}.json``
        where ``lockfile_channel`` follows the alias map (``imessage`` →
        ``bluebubbles`` so both channels share a single quota).

        Args:
            channel: One of ``whatsapp``, ``bluebubbles``, ``imessage`` (or any
                channel present in ``org_config["rate_limits"]["channels"]``).
            org_config: Parsed ``config/org.yaml`` as a dict. Missing keys fall
                back to ``_CHANNEL_DEFAULTS``; unknown channels fall back to
                ``bluebubbles`` defaults (safe conservative choice).

        Returns:
            A RateLimitGuard bound to the channel's per-channel lockfile.
        """
        defaults = _CHANNEL_DEFAULTS.get(channel, _CHANNEL_DEFAULTS["bluebubbles"])
        channel_cfg: dict[str, Any] = {}
        try:
            channel_cfg = (
                org_config.get("rate_limits", {})
                .get("channels", {})
                .get(channel, {})
            ) or {}
        except AttributeError:
            channel_cfg = {}

        max_per_day = int(channel_cfg.get("max_per_day", defaults["max_per_day"]))
        min_interval = float(
            channel_cfg.get("min_interval_seconds", defaults["min_interval_seconds"])
        )
        jitter_cfg = channel_cfg.get("jitter") or {}
        if isinstance(jitter_cfg, dict):
            jitter_min = float(jitter_cfg.get("min", defaults["jitter_min"]))
            jitter_max = float(jitter_cfg.get("max", defaults["jitter_max"]))
        elif isinstance(jitter_cfg, (list, tuple)) and len(jitter_cfg) >= 2:
            jitter_min = float(jitter_cfg[0])
            jitter_max = float(jitter_cfg[1])
        else:
            jitter_min = defaults["jitter_min"]
            jitter_max = defaults["jitter_max"]

        lockfile_channel = defaults["lockfile_channel"]
        lockfile = Path.home() / ".clawwrap" / f"ratelimit-{lockfile_channel}.json"

        return cls(
            lockfile=lockfile,
            max_per_day=max_per_day,
            min_interval_seconds=min_interval,
            jitter_min=jitter_min,
            jitter_max=jitter_max,
            _from_classmethod=True,
        )

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
