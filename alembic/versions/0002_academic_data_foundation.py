"""academic data foundation

Revision ID: 0002_academic_data_foundation
Revises: 0001_baseline
Create Date: 2026-09-15

Phase 1: establishes the six architectural schemas (raw_moodle,
raw_attendance, staging, academic, integration, auth) and the canonical
academic tables plus their integration source mappings and pipeline
observability tables. raw_moodle, raw_attendance, staging, and auth are
created empty on purpose — no source-specific tables are invented before
the real Moodle/Attendance models are studied in a later phase.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_academic_data_foundation"
down_revision: str | None = "0001_baseline"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

SCHEMAS = ("academic", "integration", "raw_moodle", "raw_attendance", "staging", "auth")


def _ts(name: str) -> sa.Column:
    """NOT NULL timezone-aware timestamp column, defaulting to now()."""
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def _ts_nullable(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=True)


def _source_mapping_columns(fk_column: str, referent: str) -> list[sa.Column]:
    """Columns shared by every integration.*_sources mapping table."""
    return [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            fk_column, sa.Integer(), sa.ForeignKey(referent, ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        _ts_nullable("source_updated_at"),
        sa.Column("source_hash", sa.Text(), nullable=True),
        _ts("first_seen_at"),
        _ts("last_seen_at"),
        _ts_nullable("synced_at"),
    ]


def _non_empty_check(table: str, column: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(
        f"length(trim({column})) > 0", name=f"ck_{table}_{column}_not_empty"
    )


def upgrade() -> None:
    for schema in SCHEMAS:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    # -- academic ---------------------------------------------------------
    op.create_table(
        "students",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_number", sa.Text(), nullable=False),
        sa.Column("first_name", sa.Text(), nullable=False),
        sa.Column("last_name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("account_number", name="uq_students_account_number"),
        schema="academic",
    )

    op.create_table(
        "courses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        _ts("created_at"),
        _ts("updated_at"),
        schema="academic",
    )

    op.create_table(
        "enrollments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "student_id",
            sa.Integer(),
            sa.ForeignKey("academic.students.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "course_id",
            sa.Integer(),
            sa.ForeignKey("academic.courses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("student_id", "course_id", name="uq_enrollments_student_course"),
        schema="academic",
    )
    op.create_index("ix_enrollments_student_id", "enrollments", ["student_id"], schema="academic")
    op.create_index("ix_enrollments_course_id", "enrollments", ["course_id"], schema="academic")

    # -- integration: source identity mappings -----------------------------
    op.create_table(
        "student_sources",
        *_source_mapping_columns("student_id", "academic.students.id"),
        sa.UniqueConstraint("source_system", "source_id", name="uq_student_sources_source"),
        _non_empty_check("student_sources", "source_system"),
        _non_empty_check("student_sources", "source_id"),
        schema="integration",
    )
    op.create_index(
        "ix_student_sources_student_id", "student_sources", ["student_id"], schema="integration"
    )

    op.create_table(
        "course_sources",
        *_source_mapping_columns("course_id", "academic.courses.id"),
        sa.UniqueConstraint("source_system", "source_id", name="uq_course_sources_source"),
        _non_empty_check("course_sources", "source_system"),
        _non_empty_check("course_sources", "source_id"),
        schema="integration",
    )
    op.create_index(
        "ix_course_sources_course_id", "course_sources", ["course_id"], schema="integration"
    )

    op.create_table(
        "enrollment_sources",
        *_source_mapping_columns("enrollment_id", "academic.enrollments.id"),
        sa.UniqueConstraint("source_system", "source_id", name="uq_enrollment_sources_source"),
        _non_empty_check("enrollment_sources", "source_system"),
        _non_empty_check("enrollment_sources", "source_id"),
        schema="integration",
    )
    op.create_index(
        "ix_enrollment_sources_enrollment_id",
        "enrollment_sources",
        ["enrollment_id"],
        schema="integration",
    )

    # -- integration: pipeline observability --------------------------------
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        _ts_nullable("snapshot_time"),
        _ts("started_at"),
        _ts_nullable("completed_at"),
        sa.Column("rows_read", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_valid", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_inserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_unchanged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("watermark_start", postgresql.JSONB(), nullable=True),
        sa.Column("watermark_end", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.UniqueConstraint("batch_id", name="uq_sync_runs_batch_id"),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'SUCCESS', 'FAILED')", name="ck_sync_runs_status"
        ),
        sa.CheckConstraint("rows_read >= 0", name="ck_sync_runs_rows_read_nonneg"),
        sa.CheckConstraint("rows_valid >= 0", name="ck_sync_runs_rows_valid_nonneg"),
        sa.CheckConstraint("rows_inserted >= 0", name="ck_sync_runs_rows_inserted_nonneg"),
        sa.CheckConstraint("rows_updated >= 0", name="ck_sync_runs_rows_updated_nonneg"),
        sa.CheckConstraint("rows_unchanged >= 0", name="ck_sync_runs_rows_unchanged_nonneg"),
        sa.CheckConstraint("rows_skipped >= 0", name="ck_sync_runs_rows_skipped_nonneg"),
        sa.CheckConstraint("error_count >= 0", name="ck_sync_runs_error_count_nonneg"),
        _non_empty_check("sync_runs", "source_system"),
        _non_empty_check("sync_runs", "entity_type"),
        schema="integration",
    )
    op.create_index(
        "ix_sync_runs_source_system", "sync_runs", ["source_system"], schema="integration"
    )
    op.create_index("ix_sync_runs_entity_type", "sync_runs", ["entity_type"], schema="integration")
    op.create_index("ix_sync_runs_started_at", "sync_runs", ["started_at"], schema="integration")
    op.create_index("ix_sync_runs_status", "sync_runs", ["status"], schema="integration")

    op.create_table(
        "sync_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("state", postgresql.JSONB(), nullable=False, server_default="{}"),
        _ts("updated_at"),
        sa.UniqueConstraint("source_system", "entity_type", name="uq_sync_state_source_entity"),
        _non_empty_check("sync_state", "source_system"),
        _non_empty_check("sync_state", "entity_type"),
        schema="integration",
    )


def downgrade() -> None:
    op.drop_table("sync_state", schema="integration")
    op.drop_table("sync_runs", schema="integration")
    op.drop_table("enrollment_sources", schema="integration")
    op.drop_table("course_sources", schema="integration")
    op.drop_table("student_sources", schema="integration")
    op.drop_table("enrollments", schema="academic")
    op.drop_table("courses", schema="academic")
    op.drop_table("students", schema="academic")

    for schema in SCHEMAS:
        op.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
