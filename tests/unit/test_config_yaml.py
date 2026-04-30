"""YAML config assertion tests (spec 085 T029 + T030).

T029: config/org.yaml contains the spec-mandated rate_limits.channels.* block
      with the exact values from the plan.
T030: clawwrap/config/outbound-policy.yaml contains the spec-mandated
      allowlists.direct.{bluebubbles,whatsapp,imessage} entries AND preserves
      all existing shared.* entries (regression guard).
"""
from __future__ import annotations

from pathlib import Path

import yaml

# Repo-root org.yaml: clawwrap/tests/unit/test_config_yaml.py
#   parents[0] = tests/unit
#   parents[1] = tests
#   parents[2] = clawwrap
#   parents[3] = <repo-root>
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ORG_YAML = _REPO_ROOT / "config" / "org.yaml"
_POLICY_YAML = _REPO_ROOT / "clawwrap" / "config" / "outbound-policy.yaml"


def _load(path: Path) -> dict:
    assert path.is_file(), f"expected YAML at {path}"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path} must parse to a dict"
    return data


class TestOrgYamlRateLimits:
    def test_whatsapp_rate_limits_present(self) -> None:
        """T029-a: whatsapp rate limits match spec."""
        cfg = _load(_ORG_YAML)
        wa = cfg["rate_limits"]["channels"]["whatsapp"]
        assert wa["max_per_day"] == 3
        assert wa["min_interval_seconds"] == 60
        # jitter is [min, max] inclusive
        assert list(wa["jitter"]) == [10, 15]

    def test_bluebubbles_rate_limits_present(self) -> None:
        """T029-b: bluebubbles rate limits match spec, including new_conversations_per_day."""
        cfg = _load(_ORG_YAML)
        bb = cfg["rate_limits"]["channels"]["bluebubbles"]
        assert bb["max_per_day"] == 20
        assert bb["min_interval_seconds"] == 30
        assert list(bb["jitter"]) == [3, 5]
        assert bb["new_conversations_per_day"] == 5


class TestOutboundPolicyDirectAllowlists:
    def test_direct_allowlists_include_new_channels(self) -> None:
        """T030-a: bluebubbles, whatsapp, imessage direct allowlists contain ['*']."""
        policy = _load(_POLICY_YAML)
        direct = policy["allowlists"]["direct"]
        assert direct["bluebubbles"] == ["*"]
        assert direct["whatsapp"] == ["*"]
        assert direct["imessage"] == ["*"]

    def test_shared_allowlists_preserved(self) -> None:
        """T030-b: regression — shared.mailchimp / shared.resend-broadcast /
        shared.keap entries are untouched after the direct.* additions."""
        policy = _load(_POLICY_YAML)
        shared = policy["allowlists"]["shared"]
        assert "mailchimp" in shared
        assert "resend-broadcast" in shared
        assert "keap" in shared
        # Exact values should still be the pre-085 contents.
        assert shared["mailchimp"] == ["ceremonia-webinar.full-list"]
        assert "keap-campaign.sequence-trigger" in shared["keap"]
