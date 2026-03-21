"""Unit tests for the OpenClaw group.identity_matches handler."""
from __future__ import annotations

import subprocess

import pytest

from clawwrap.adapters.openclaw.handlers import group_identity


def test_run_wacli_matches_current_group_name(monkeypatch: pytest.MonkeyPatch) -> None:
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=b'{"success":true,"data":{"Name":"Awaken Apr 2026 Staff"}}',
        stderr=b"",
    )
    monkeypatch.setattr(group_identity.subprocess, "run", lambda *args, **kwargs: completed)

    matched, detail = group_identity._run_wacli(
        "120363405933229321@g.us",
        "Awaken Apr 2026 Staff",
    )

    assert matched is True
    assert "matched group title" in detail


def test_run_wacli_reports_name_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=b'{"success":true,"data":{"Name":"Wrong Group"}}',
        stderr=b"",
    )
    monkeypatch.setattr(group_identity.subprocess, "run", lambda *args, **kwargs: completed)

    matched, detail = group_identity._run_wacli(
        "120363405933229321@g.us",
        "Awaken Apr 2026 Staff",
    )

    assert matched is False
    assert "Wrong Group" in detail
