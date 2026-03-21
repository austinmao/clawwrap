"""Unit tests for gate/audit.py — structured YAML logging."""
from __future__ import annotations

from pathlib import Path

import yaml

from clawwrap.gate.audit import log_verdict


class TestLogVerdict:
    def _sample_verdict(self) -> dict:
        return {
            "request_id": "gate-123-abcd",
            "allowed": True,
            "target": "jid@g.us",
            "channel": "whatsapp",
            "requested_by": "test-skill",
            "checks": [{"name": "target_exists", "passed": True, "detail": "ok"}],
            "timestamp": "2026-03-15T12:00:00+00:00",
        }

    def test_writes_valid_yaml(self, tmp_path: Path) -> None:
        result = log_verdict(self._sample_verdict(), tmp_path)
        assert result["logged"] is True
        assert result["request_id"] == "gate-123-abcd"
        # Verify the file contains valid YAML
        log_files = list(tmp_path.glob("*.yaml"))
        assert len(log_files) == 1
        entries = yaml.safe_load(log_files[0].read_text())
        assert isinstance(entries, list)
        assert len(entries) == 1
        assert entries[0]["request_id"] == "gate-123-abcd"

    def test_appends_to_existing(self, tmp_path: Path) -> None:
        log_verdict(self._sample_verdict(), tmp_path)
        second = self._sample_verdict()
        second["request_id"] = "gate-456-efgh"
        log_verdict(second, tmp_path)
        log_files = list(tmp_path.glob("*.yaml"))
        entries = yaml.safe_load(log_files[0].read_text())
        assert len(entries) == 2
        assert entries[1]["request_id"] == "gate-456-efgh"

    def test_handles_write_failure_gracefully(self, tmp_path: Path) -> None:
        # Use a path that can't be created (file instead of directory)
        bad_path = tmp_path / "file.txt"
        bad_path.write_text("not a directory")
        # log_verdict should not raise
        result = log_verdict(self._sample_verdict(), bad_path / "subdir")
        assert result["logged"] is False
