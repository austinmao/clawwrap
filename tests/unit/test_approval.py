"""T064: Unit tests for clawwrap.model.approval.

Covers:
- compute_approval_hash is deterministic (same inputs = same hash)
- Different inputs produce different hashes
- ApprovalRole lattice: operator < approver < admin
- Role collapse: highest-required-role-wins
- DriftExceptionRecord.new enforces role >= original_apply_role
- ApprovalRecord.new creates a valid record
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timezone
from typing import Any

import pytest

from clawwrap.model.approval import (
    ApprovalIdentityEvidence,
    ApprovalRecord,
    DriftExceptionRecord,
    compute_approval_hash,
)
from clawwrap.model.types import ApprovalRole

# ---------------------------------------------------------------------------
# compute_approval_hash
# ---------------------------------------------------------------------------


class TestComputeApprovalHash:
    """Tests for compute_approval_hash determinism and uniqueness."""

    def test_same_inputs_produce_same_hash(self) -> None:
        """Identical dicts must produce identical SHA-256 hashes."""
        inputs: dict[str, Any] = {"key": "value", "count": 3}
        h1 = compute_approval_hash(inputs)
        h2 = compute_approval_hash(inputs)
        assert h1 == h2

    def test_different_inputs_produce_different_hashes(self) -> None:
        """Dicts with different values must produce different hashes."""
        h1 = compute_approval_hash({"key": "alpha"})
        h2 = compute_approval_hash({"key": "beta"})
        assert h1 != h2

    def test_hash_is_hex_string(self) -> None:
        """Hash output must be a lowercase hexadecimal string."""
        h = compute_approval_hash({"x": 1})
        assert isinstance(h, str)
        assert all(c in "0123456789abcdef" for c in h)

    def test_hash_length_is_64_chars(self) -> None:
        """SHA-256 hash must be 64 hex characters long."""
        h = compute_approval_hash({"x": 1})
        assert len(h) == 64

    def test_key_order_does_not_affect_hash(self) -> None:
        """Dict key insertion order must not change the hash (sort_keys=True)."""
        h1 = compute_approval_hash({"a": 1, "b": 2})
        h2 = compute_approval_hash({"b": 2, "a": 1})
        assert h1 == h2

    def test_empty_dict_hashes_consistently(self) -> None:
        """Empty dict must hash to the same value every time."""
        h1 = compute_approval_hash({})
        h2 = compute_approval_hash({})
        assert h1 == h2

    def test_none_value_in_dict_is_handled(self) -> None:
        """Dict with None values must produce a consistent hash."""
        h1 = compute_approval_hash({"key": None})
        h2 = compute_approval_hash({"key": None})
        assert h1 == h2

    def test_nested_dict_is_deterministic(self) -> None:
        """Nested dicts must produce a deterministic hash."""
        nested: dict[str, Any] = {"outer": {"inner": [1, 2, 3]}}
        h1 = compute_approval_hash(nested)
        h2 = compute_approval_hash(nested)
        assert h1 == h2


# ---------------------------------------------------------------------------
# ApprovalRole lattice
# ---------------------------------------------------------------------------


class TestApprovalRoleLattice:
    """Tests for ApprovalRole enum ordering comparisons."""

    def test_operator_less_than_approver(self) -> None:
        """operator < approver."""
        assert ApprovalRole.operator < ApprovalRole.approver

    def test_approver_less_than_admin(self) -> None:
        """approver < admin."""
        assert ApprovalRole.approver < ApprovalRole.admin

    def test_operator_less_than_admin(self) -> None:
        """operator < admin (transitive)."""
        assert ApprovalRole.operator < ApprovalRole.admin

    def test_admin_greater_than_operator(self) -> None:
        """admin > operator."""
        assert ApprovalRole.admin > ApprovalRole.operator

    def test_admin_greater_than_approver(self) -> None:
        """admin > approver."""
        assert ApprovalRole.admin > ApprovalRole.approver

    def test_same_role_equal(self) -> None:
        """A role must equal itself."""
        assert ApprovalRole.operator == ApprovalRole.operator
        assert ApprovalRole.approver == ApprovalRole.approver
        assert ApprovalRole.admin == ApprovalRole.admin

    def test_operator_lte_operator(self) -> None:
        """operator <= operator must be True."""
        assert ApprovalRole.operator <= ApprovalRole.operator

    def test_admin_gte_admin(self) -> None:
        """admin >= admin must be True."""
        assert ApprovalRole.admin >= ApprovalRole.admin

    def test_approver_lte_admin(self) -> None:
        """approver <= admin must be True."""
        assert ApprovalRole.approver <= ApprovalRole.admin

    def test_admin_not_less_than_operator(self) -> None:
        """admin < operator must be False."""
        assert not (ApprovalRole.admin < ApprovalRole.operator)

    def test_comparison_with_non_role_returns_not_implemented(self) -> None:
        """Comparing ApprovalRole against a non-ApprovalRole must return NotImplemented."""
        result = ApprovalRole.operator.__ge__("operator")
        assert result is NotImplemented


# ---------------------------------------------------------------------------
# Role collapse: highest-required-role-wins
# ---------------------------------------------------------------------------


class TestRoleCollapse:
    """Tests for role selection logic (highest required role wins)."""

    def test_max_of_roles_is_admin(self) -> None:
        """max() over roles must return admin as the highest."""
        roles = [ApprovalRole.operator, ApprovalRole.approver, ApprovalRole.admin]
        assert max(roles) == ApprovalRole.admin

    def test_max_of_two_roles_is_higher(self) -> None:
        """max() between operator and approver must return approver."""
        assert max(ApprovalRole.operator, ApprovalRole.approver) == ApprovalRole.approver

    def test_min_of_roles_is_operator(self) -> None:
        """min() over roles must return operator as the lowest."""
        roles = [ApprovalRole.admin, ApprovalRole.approver, ApprovalRole.operator]
        assert min(roles) == ApprovalRole.operator

    def test_required_role_gate(self) -> None:
        """Simulated gate: user role must be >= required role to pass."""
        required = ApprovalRole.approver

        assert ApprovalRole.admin >= required
        assert ApprovalRole.approver >= required
        assert not (ApprovalRole.operator >= required)


# ---------------------------------------------------------------------------
# ApprovalRecord.new
# ---------------------------------------------------------------------------


class TestApprovalRecordNew:
    """Tests for ApprovalRecord.new factory method."""

    def _make_evidence(self) -> ApprovalIdentityEvidence:
        return ApprovalIdentityEvidence(
            identity_source="local-cli",
            subject_id="tester@example.com",
            issued_at=datetime.now(tz=timezone.utc),
            trust_basis="local-cli-development",
        )

    def test_new_creates_valid_record(self) -> None:
        """ApprovalRecord.new must create a valid record with valid=True."""
        run_id = uuid.uuid4()
        evidence = self._make_evidence()
        record = ApprovalRecord.new(
            run_id=run_id,
            resolved_inputs={"key": "val"},
            evidence=evidence,
            role=ApprovalRole.operator,
        )

        assert record.valid is True
        assert record.run_id == run_id
        assert record.role == ApprovalRole.operator
        assert record.invalidated_at is None
        assert record.invalidation_reason is None

    def test_new_computes_hash_from_inputs(self) -> None:
        """The approval_hash must match compute_approval_hash of the inputs."""
        from clawwrap.model.approval import compute_approval_hash

        inputs: dict[str, Any] = {"key": "value", "num": 42}
        evidence = self._make_evidence()
        record = ApprovalRecord.new(
            run_id=uuid.uuid4(),
            resolved_inputs=inputs,
            evidence=evidence,
            role=ApprovalRole.operator,
        )

        assert record.approval_hash == compute_approval_hash(inputs)

    def test_new_assigns_unique_id(self) -> None:
        """Each ApprovalRecord.new call must produce a distinct UUID."""
        evidence = self._make_evidence()
        r1 = ApprovalRecord.new(uuid.uuid4(), {}, evidence, ApprovalRole.operator)
        r2 = ApprovalRecord.new(uuid.uuid4(), {}, evidence, ApprovalRole.operator)
        assert r1.id != r2.id


# ---------------------------------------------------------------------------
# DriftExceptionRecord.new — lattice constraint
# ---------------------------------------------------------------------------


class TestDriftExceptionRecordNew:
    """Tests for DriftExceptionRecord.new role constraint."""

    def _ids(self) -> tuple[uuid.UUID, uuid.UUID]:
        return uuid.uuid4(), uuid.uuid4()

    def test_same_role_is_allowed(self) -> None:
        """Exception role equal to original_apply_role must be allowed."""
        run_id, conformance_id = self._ids()
        record = DriftExceptionRecord.new(
            run_id=run_id,
            conformance_id=conformance_id,
            reason="Accepted by operator",
            identity_source="local-cli",
            subject_id="user@example.com",
            role=ApprovalRole.operator,
            original_apply_role=ApprovalRole.operator,
        )
        assert record.role == ApprovalRole.operator

    def test_higher_role_is_allowed(self) -> None:
        """Exception role higher than original_apply_role must be allowed."""
        run_id, conformance_id = self._ids()
        record = DriftExceptionRecord.new(
            run_id=run_id,
            conformance_id=conformance_id,
            reason="Escalated approval",
            identity_source="local-cli",
            subject_id="admin@example.com",
            role=ApprovalRole.admin,
            original_apply_role=ApprovalRole.operator,
        )
        assert record.role == ApprovalRole.admin

    def test_lower_role_raises_value_error(self) -> None:
        """Exception role lower than original_apply_role must raise ValueError."""
        run_id, conformance_id = self._ids()
        with pytest.raises(ValueError, match="must be >="):
            DriftExceptionRecord.new(
                run_id=run_id,
                conformance_id=conformance_id,
                reason="Insufficient authority",
                identity_source="local-cli",
                subject_id="operator@example.com",
                role=ApprovalRole.operator,
                original_apply_role=ApprovalRole.admin,
            )

    def test_approver_lower_than_admin_raises(self) -> None:
        """Approver role < admin original_apply_role must raise ValueError."""
        run_id, conformance_id = self._ids()
        with pytest.raises(ValueError):
            DriftExceptionRecord.new(
                run_id=run_id,
                conformance_id=conformance_id,
                reason="Not enough authority",
                identity_source="local-cli",
                subject_id="approver@example.com",
                role=ApprovalRole.approver,
                original_apply_role=ApprovalRole.admin,
            )

    def test_new_assigns_recorded_at(self) -> None:
        """DriftExceptionRecord.new must set recorded_at to a recent timestamp."""
        run_id, conformance_id = self._ids()
        before = datetime.now(UTC)
        record = DriftExceptionRecord.new(
            run_id=run_id,
            conformance_id=conformance_id,
            reason="Reason",
            identity_source="local-cli",
            subject_id="user",
            role=ApprovalRole.admin,
            original_apply_role=ApprovalRole.operator,
        )
        after = datetime.now(UTC)
        assert before <= record.recorded_at <= after
