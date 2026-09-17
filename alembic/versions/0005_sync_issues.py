"""generic operational issue tracking: integration.sync_issues

Revision ID: 0005_sync_issues
Revises: 0004_attendance_ingestion
Create Date: 2026-09-17

Adds integration.sync_issues: a generic, queryable record of skipped
inconsistencies (e.g. an Attendance student whose account_number doesn't
resolve to any academic student yet), so they stay visible instead of
disappearing into a rows_skipped counter. Not specific to any one
source_system or pipeline — academic.*/integration.*_sources/
raw_attendance.*/staging.* are all unchanged by this migration.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_sync_issues"
down_revision: str | None = "0004_attendance_ingestion"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sync_issues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("issue_type", sa.Text(), nullable=False),
        sa.Column("source_entity", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("reference_value", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "source_system",
            "issue_type",
            "source_entity",
            "source_id",
            name="uq_sync_issues_identity",
        ),
        sa.CheckConstraint("status IN ('OPEN', 'RESOLVED')", name="ck_sync_issues_status"),
        sa.CheckConstraint(
            "length(trim(source_system)) > 0", name="ck_sync_issues_source_system_not_empty"
        ),
        sa.CheckConstraint(
            "length(trim(issue_type)) > 0", name="ck_sync_issues_issue_type_not_empty"
        ),
        sa.CheckConstraint(
            "length(trim(source_entity)) > 0", name="ck_sync_issues_source_entity_not_empty"
        ),
        sa.CheckConstraint(
            "length(trim(source_id)) > 0", name="ck_sync_issues_source_id_not_empty"
        ),
        schema="integration",
    )
    op.create_index("ix_sync_issues_status", "sync_issues", ["status"], schema="integration")
    op.create_index(
        "ix_sync_issues_source_system", "sync_issues", ["source_system"], schema="integration"
    )
    op.create_index(
        "ix_sync_issues_issue_type", "sync_issues", ["issue_type"], schema="integration"
    )
    op.create_index(
        "ix_sync_issues_reference_value", "sync_issues", ["reference_value"], schema="integration"
    )


def downgrade() -> None:
    op.drop_table("sync_issues", schema="integration")
