"""Doppler secret provider — resolves secret references via the doppler CLI.

Requires the ``doppler`` binary to be installed and authenticated.
Fail-hard policy: if Doppler is unreachable the operation raises
``DopplerUnavailableError`` rather than silently returning empty values.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Final

# Exit code returned by subprocess when the doppler command itself fails.
_DOPPLER_CMD_NOT_FOUND_MSG: Final[str] = "No such file or directory"

# Maximum seconds to wait for a doppler subprocess call.
_DOPPLER_TIMEOUT_SECONDS: Final[int] = 10


class DopplerUnavailableError(RuntimeError):
    """Raised when the Doppler CLI cannot be reached."""


class DopplerSecretNotFoundError(KeyError):
    """Raised when a requested secret does not exist in Doppler."""


def _run_doppler(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Execute a doppler subcommand and return the completed process.

    Args:
        args: CLI arguments following ``doppler``.

    Returns:
        CompletedProcess with captured stdout/stderr.

    Raises:
        DopplerUnavailableError: If doppler is not installed or times out.
    """
    cmd = ["doppler", *args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_DOPPLER_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        raise DopplerUnavailableError(
            "doppler CLI not found. Install from https://docs.doppler.com/docs/install-cli"
        ) from None
    except subprocess.TimeoutExpired:
        raise DopplerUnavailableError(
            f"doppler CLI timed out after {_DOPPLER_TIMEOUT_SECONDS}s"
        ) from None
    return result


def resolve_secret(ref: str) -> str:
    """Resolve a Doppler secret reference to its plaintext value.

    Args:
        ref: Secret name / reference key (e.g. ``MY_API_KEY``).

    Returns:
        Plaintext secret value.

    Raises:
        DopplerUnavailableError: If the Doppler CLI cannot be reached.
        DopplerSecretNotFoundError: If the secret does not exist.
    """
    result = _run_doppler(["secrets", "get", ref, "--plain"])
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "does not exist" in stderr or "not found" in stderr.lower():
            raise DopplerSecretNotFoundError(
                f"Secret '{ref}' not found in Doppler: {stderr}"
            )
        raise DopplerUnavailableError(
            f"doppler secrets get failed (exit {result.returncode}): {stderr}"
        )
    return result.stdout.strip()


def validate_references(refs: list[str]) -> list[str]:
    """Check that all secret references exist in Doppler without resolving values.

    This performs a lightweight presence check by listing secret names and
    comparing rather than fetching each value.  No secret values are printed
    to stdout or stderr.

    Args:
        refs: List of secret reference keys to check.

    Returns:
        List of reference keys that are invalid or do not exist.
        An empty list means all references are valid.

    Raises:
        DopplerUnavailableError: If the Doppler CLI cannot be reached.
    """
    if not refs:
        return []

    # Fetch all secret names (not values) from the configured project/config.
    result = _run_doppler(["secrets", "--only-names"])
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise DopplerUnavailableError(
            f"doppler secrets --only-names failed (exit {result.returncode}): {stderr}"
        )

    available: set[str] = {
        line.strip() for line in result.stdout.splitlines() if line.strip()
    }

    invalid: list[str] = [ref for ref in refs if ref not in available]
    return invalid


def _print_err(msg: str) -> None:
    """Write a message to stderr (utility for __main__ usage)."""
    print(msg, file=sys.stderr)
