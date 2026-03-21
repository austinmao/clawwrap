"""Initial schema — all clawwrap tables.

Revision ID: 001
Revises: (none)
Create Date: 2026-03-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Alembic metadata
revision = "001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = "clawwrap"


def upgrade() -> None:
    """Create all clawwrap tables, ENUMs, foreign keys, and indexes."""

    # -----------------------------------------------------------------
    # ENUM types
    # -----------------------------------------------------------------
    run_phase_enum = postgresql.ENUM(
        "resolve", "verify", "approve", "execute", "audit",
        name="run_phase",
        schema=SCHEMA,
        create_type=False,
    )
    run_status_enum = postgresql.ENUM(
        "pending",
        "resolving",
        "verifying",
        "awaiting_approval",
        "approved",
        "executing",
        "auditing",
        "planned",
        "host_apply_in_progress",
        "conformance_pending",
        "applied",
        "drifted",
        "exception_recorded",
        "failed",
        "cancelled",
        "not_checked",
        name="run_status",
        schema=SCHEMA,
        create_type=False,
    )
    approval_role_enum = postgresql.ENUM(
        "operator", "approver", "admin",
        name="approval_role",
        schema=SCHEMA,
        create_type=False,
    )
    conformance_status_enum = postgresql.ENUM(
        "matching", "drifted", "not_checked",
        name="conformance_status",
        schema=SCHEMA,
        create_type=False,
    )
    legacy_source_type_enum = postgresql.ENUM(
        "prompt", "config",
        name="legacy_source_type",
        schema=SCHEMA,
        create_type=False,
    )
    legacy_expected_status_enum = postgresql.ENUM(
        "removed", "disabled", "shadowed_unreachable",
        name="legacy_expected_status",
        schema=SCHEMA,
        create_type=False,
    )

    # Create the ENUMs explicitly (create_type=False means they won't be
    # created automatically by Column definitions below)
    run_phase_enum.create(op.get_bind(), checkfirst=True)
    run_status_enum.create(op.get_bind(), checkfirst=True)
    approval_role_enum.create(op.get_bind(), checkfirst=True)
    conformance_status_enum.create(op.get_bind(), checkfirst=True)
    legacy_source_type_enum.create(op.get_bind(), checkfirst=True)
    legacy_expected_status_enum.create(op.get_bind(), checkfirst=True)

    # -----------------------------------------------------------------
    # Table: runs
    # -----------------------------------------------------------------
    op.create_table(
        "runs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("wrapper_name", sa.Text(), nullable=False),
        sa.Column("wrapper_version", sa.Text(), nullable=False),
        sa.Column("adapter_name", sa.Text(), nullable=False),
        sa.Column(
            "current_phase",
            postgresql.ENUM(
                "resolve", "verify", "approve", "execute", "audit",
                name="run_phase",
                schema=SCHEMA,
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending", "resolving", "verifying", "awaiting_approval",
                "approved", "executing", "auditing", "planned",
                "host_apply_in_progress", "conformance_pending", "applied",
                "drifted", "exception_recorded", "failed", "cancelled", "not_checked",
                name="run_status",
                schema=SCHEMA,
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("resolved_inputs", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_runs_wrapper_name", "runs", ["wrapper_name"], schema=SCHEMA)
    op.create_index("ix_runs_status", "runs", ["status"], schema=SCHEMA)
    op.create_index("ix_runs_created_at", "runs", ["created_at"], schema=SCHEMA)

    # -----------------------------------------------------------------
    # Table: stage_transitions
    # -----------------------------------------------------------------
    op.create_table(
        "stage_transitions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column(
            "from_phase",
            postgresql.ENUM(
                "resolve", "verify", "approve", "execute", "audit",
                name="run_phase",
                schema=SCHEMA,
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "to_phase",
            postgresql.ENUM(
                "resolve", "verify", "approve", "execute", "audit",
                name="run_phase",
                schema=SCHEMA,
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "transitioned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("evidence", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"],
            [f"{SCHEMA}.runs.id"],
            name="fk_stage_transitions_run_id",
            ondelete="CASCADE",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_stage_transitions_run_id",
        "stage_transitions",
        ["run_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_stage_transitions_transitioned_at",
        "stage_transitions",
        ["transitioned_at"],
        schema=SCHEMA,
    )

    # -----------------------------------------------------------------
    # Table: approval_records
    # -----------------------------------------------------------------
    op.create_table(
        "approval_records",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=False),
            nullable=False,
            unique=True,
        ),
        sa.Column("approval_hash", sa.Text(), nullable=False),
        sa.Column("identity_source", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trust_basis", sa.Text(), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(
                "operator", "approver", "admin",
                name="approval_role",
                schema=SCHEMA,
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "valid",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidation_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"],
            [f"{SCHEMA}.runs.id"],
            name="fk_approval_records_run_id",
            ondelete="CASCADE",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_approval_records_run_id",
        "approval_records",
        ["run_id"],
        schema=SCHEMA,
    )

    # -----------------------------------------------------------------
    # Table: apply_plans
    # -----------------------------------------------------------------
    op.create_table(
        "apply_plans",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("plan_content", postgresql.JSONB(), nullable=False),
        sa.Column("patch_items", postgresql.JSONB(), nullable=False),
        sa.Column("ownership_manifest", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("approval_hash", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"],
            [f"{SCHEMA}.runs.id"],
            name="fk_apply_plans_run_id",
            ondelete="CASCADE",
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_apply_plans_run_id", "apply_plans", ["run_id"], schema=SCHEMA)

    # -----------------------------------------------------------------
    # Table: conformance_results
    # -----------------------------------------------------------------
    op.create_table(
        "conformance_results",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "matching", "drifted", "not_checked",
                name="conformance_status",
                schema=SCHEMA,
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            [f"{SCHEMA}.runs.id"],
            name="fk_conformance_results_run_id",
            ondelete="CASCADE",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_conformance_results_run_id",
        "conformance_results",
        ["run_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_conformance_results_status",
        "conformance_results",
        ["status"],
        schema=SCHEMA,
    )

    # -----------------------------------------------------------------
    # Table: drift_exceptions
    # -----------------------------------------------------------------
    op.create_table(
        "drift_exceptions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("conformance_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("identity_source", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(
                "operator", "approver", "admin",
                name="approval_role",
                schema=SCHEMA,
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "original_apply_role",
            postgresql.ENUM(
                "operator", "approver", "admin",
                name="approval_role",
                schema=SCHEMA,
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            [f"{SCHEMA}.runs.id"],
            name="fk_drift_exceptions_run_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conformance_id"],
            [f"{SCHEMA}.conformance_results.id"],
            name="fk_drift_exceptions_conformance_id",
            ondelete="CASCADE",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_drift_exceptions_run_id", "drift_exceptions", ["run_id"], schema=SCHEMA
    )
    op.create_index(
        "ix_drift_exceptions_conformance_id",
        "drift_exceptions",
        ["conformance_id"],
        schema=SCHEMA,
    )

    # -----------------------------------------------------------------
    # Table: legacy_authority_entries
    # -----------------------------------------------------------------
    op.create_table(
        "legacy_authority_entries",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("flow_name", sa.Text(), nullable=False),
        sa.Column(
            "source_type",
            postgresql.ENUM(
                "prompt", "config",
                name="legacy_source_type",
                schema=SCHEMA,
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column(
            "expected_status",
            postgresql.ENUM(
                "removed", "disabled", "shadowed_unreachable",
                name="legacy_expected_status",
                schema=SCHEMA,
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "verified_status",
            postgresql.ENUM(
                "removed", "disabled", "shadowed_unreachable",
                name="legacy_expected_status",
                schema=SCHEMA,
                create_type=False,
            ),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "flow_name",
            "source_path",
            name="uq_legacy_authority_entries_flow_source",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_legacy_authority_entries_flow_name",
        "legacy_authority_entries",
        ["flow_name"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    """Drop all clawwrap tables and ENUMs in reverse dependency order."""
    op.drop_table("legacy_authority_entries", schema=SCHEMA)
    op.drop_table("drift_exceptions", schema=SCHEMA)
    op.drop_table("conformance_results", schema=SCHEMA)
    op.drop_table("apply_plans", schema=SCHEMA)
    op.drop_table("approval_records", schema=SCHEMA)
    op.drop_table("stage_transitions", schema=SCHEMA)
    op.drop_table("runs", schema=SCHEMA)

    # Drop ENUMs
    bind = op.get_bind()
    for enum_name in (
        "run_phase",
        "run_status",
        "approval_role",
        "conformance_status",
        "legacy_source_type",
        "legacy_expected_status",
    ):
        postgresql.ENUM(name=enum_name, schema=SCHEMA).drop(bind, checkfirst=True)
