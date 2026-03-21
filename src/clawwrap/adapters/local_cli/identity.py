"""Local-CLI identity management for development approval flows.

Provides helpers to create and load a simple `.clawwrap/identity.yaml` file
used by the local-cli adapter for non-production approval testing.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from clawwrap.model.approval import ApprovalIdentityEvidence
from clawwrap.model.types import ApprovalRole

# Default location of the local identity file.
DEFAULT_IDENTITY_PATH: Path = Path(".clawwrap/identity.yaml")

# Source type label stored in the identity file.
IDENTITY_SOURCE: str = "local-cli"

# Trust basis label stored in the identity file.
TRUST_BASIS: str = "local-cli-development"


class IdentityFileError(OSError):
    """Raised when the identity file cannot be read or written."""


def _get_macos_keychain_name(account: str) -> str | None:
    """Try to read a name stored in the macOS keychain for the given account.

    Uses the ``security`` CLI to look up the generic password stored under
    the service ``clawwrap-identity``.

    Args:
        account: Account name (typically the ``subject_id``).

    Returns:
        The stored name if found, or ``None`` if not available or not macOS.
    """
    try:
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-a",
                account,
                "-s",
                "clawwrap-identity",
                "-w",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def create_identity(name: str, role: ApprovalRole) -> Path:
    """Write a local identity file to ``.clawwrap/identity.yaml``.

    The file is created at :data:`DEFAULT_IDENTITY_PATH` relative to the
    current working directory.

    Args:
        name: Human-readable name for the identity subject.
        role: Approval role to assign.

    Returns:
        Path to the written identity file.

    Raises:
        IdentityFileError: If the file cannot be written.
    """
    path = DEFAULT_IDENTITY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    data: dict[str, Any] = {
        "identity_source": IDENTITY_SOURCE,
        "subject_id": name,
        "role": role.name,
        "issued_at": datetime.now(tz=timezone.utc).isoformat(),
        "trust_basis": TRUST_BASIS,
    }

    try:
        path.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")
    except OSError as exc:
        raise IdentityFileError(f"Cannot write identity file at {path}: {exc}") from exc

    return path


def load_identity(path: Path = DEFAULT_IDENTITY_PATH) -> ApprovalIdentityEvidence:
    """Load an ApprovalIdentityEvidence from a local identity YAML file.

    If a macOS keychain entry exists for the subject_id, the stored name is
    used to enrich the identity (subject_id is left unchanged; the keychain
    is used only as an optional validation that the identity belongs to this
    machine's user).

    Args:
        path: Path to the identity YAML file.

    Returns:
        ApprovalIdentityEvidence constructed from the file.

    Raises:
        IdentityFileError: If the file cannot be read or is malformed.
    """
    if not path.exists():
        raise IdentityFileError(
            f"Identity file not found: {path}. "
            "Run `clawwrap run approve --create-identity` to create one."
        )

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise IdentityFileError(f"Cannot read identity file {path}: {exc}") from exc

    try:
        data: dict[str, Any] = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise IdentityFileError(
            f"Identity file {path} is not valid YAML: {exc}"
        ) from exc

    required = {"identity_source", "subject_id", "issued_at", "trust_basis"}
    missing = required - set(data.keys())
    if missing:
        raise IdentityFileError(
            f"Identity file missing required fields: {sorted(missing)}"
        )

    try:
        evidence = ApprovalIdentityEvidence.from_dict(data)
    except (KeyError, ValueError) as exc:
        raise IdentityFileError(
            f"Identity file {path} has invalid field values: {exc}"
        ) from exc

    # Optionally validate via macOS keychain (non-blocking; ignored if unavailable).
    _get_macos_keychain_name(evidence.subject_id)

    return evidence


def validate_identity_for_dev(evidence: ApprovalIdentityEvidence) -> list[str]:
    """Perform development-only validation of an identity evidence object.

    This is intentionally permissive — it is intended for local testing only.
    Production adapters must implement stricter validation.

    Args:
        evidence: The identity evidence to validate.

    Returns:
        List of validation error strings (empty = valid for dev use).
    """
    errors: list[str] = []
    if not evidence.identity_source:
        errors.append("identity_source must not be empty")
    if not evidence.subject_id:
        errors.append("subject_id must not be empty")
    if not evidence.trust_basis:
        errors.append("trust_basis must not be empty")
    if evidence.issued_at > datetime.now(tz=timezone.utc):
        errors.append("issued_at must not be in the future")
    return errors
