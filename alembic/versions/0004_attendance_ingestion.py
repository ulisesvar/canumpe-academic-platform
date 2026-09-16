"""attendance ingestion: canonical attendance tables, source mappings,
raw_attendance and staging tables

Revision ID: 0004_attendance_ingestion
Revises: 0003_moodle_ingestion
Create Date: 2026-09-16

Phase 3: adds the canonical academic.attendance_sessions/
attendance_records tables, their integration.*_sources mappings, and the
raw_attendance.*/staging.attendance_* tables used by the Attendance
ingestion pipeline. academic.students/courses, integration.student_sources
and integration.course_sources already exist and are unchanged —
Attendance reconciles to the existing canonical student population via
integration.student_sources (source_system='attendance') and resolves
its course via integration.course_sources (source_system='moodle');
this migration never touches those tables' data.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_attendance_ingestion"
down_revision: str | None = "0003_moodle_ingestion"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # -- academic: canonical attendance structures ---------------------------
    op.create_table(
        "attendance_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "course_id",
            sa.Integer(),
            sa.ForeignKey("academic.courses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("status IN ('OPEN', 'CLOSED')", name="ck_attendance_sessions_status"),
        schema="academic",
    )
    op.create_index(
        "ix_attendance_sessions_course_id", "attendance_sessions", ["course_id"], schema="academic"
    )

    op.create_table(
        "attendance_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "attendance_session_id",
            sa.Integer(),
            sa.ForeignKey("academic.attendance_sessions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            sa.Integer(),
            sa.ForeignKey("academic.students.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "attendance_session_id", "student_id", name="uq_attendance_records_session_student"
        ),
        schema="academic",
    )
    op.create_index(
        "ix_attendance_records_attendance_session_id",
        "attendance_records",
        ["attendance_session_id"],
        schema="academic",
    )
    op.create_index(
        "ix_attendance_records_student_id", "attendance_records", ["student_id"], schema="academic"
    )

    # -- integration: source identity mappings -------------------------------
    op.create_table(
        "attendance_session_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "attendance_session_id",
            sa.Integer(),
            sa.ForeignKey("academic.attendance_sessions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_hash", sa.Text(), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "source_system", "source_id", name="uq_attendance_session_sources_source"
        ),
        sa.CheckConstraint(
            "length(trim(source_system)) > 0",
            name="ck_attendance_session_sources_source_system_not_empty",
        ),
        sa.CheckConstraint(
            "length(trim(source_id)) > 0", name="ck_attendance_session_sources_source_id_not_empty"
        ),
        schema="integration",
    )
    op.create_index(
        "ix_attendance_session_sources_attendance_session_id",
        "attendance_session_sources",
        ["attendance_session_id"],
        schema="integration",
    )

    op.create_table(
        "attendance_record_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "attendance_record_id",
            sa.Integer(),
            sa.ForeignKey("academic.attendance_records.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_hash", sa.Text(), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "source_system", "source_id", name="uq_attendance_record_sources_source"
        ),
        sa.CheckConstraint(
            "length(trim(source_system)) > 0",
            name="ck_attendance_record_sources_source_system_not_empty",
        ),
        sa.CheckConstraint(
            "length(trim(source_id)) > 0", name="ck_attendance_record_sources_source_id_not_empty"
        ),
        schema="integration",
    )
    op.create_index(
        "ix_attendance_record_sources_attendance_record_id",
        "attendance_record_sources",
        ["attendance_record_id"],
        schema="integration",
    )

    # -- raw_attendance: faithful, append-only landing copies ----------------
    op.create_table(
        "students",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("account_number", sa.Text(), nullable=True),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_hash", sa.Text(), nullable=False),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "batch_id", "source_id", name="uq_raw_attendance_students_batch_source"
        ),
        schema="raw_attendance",
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("source_hash", sa.Text(), nullable=False),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "batch_id", "source_id", name="uq_raw_attendance_sessions_batch_source"
        ),
        schema="raw_attendance",
    )

    op.create_table(
        "attendances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("student_source_id", sa.Text(), nullable=True),
        sa.Column("session_source_id", sa.Text(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_hash", sa.Text(), nullable=False),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "batch_id", "source_id", name="uq_raw_attendance_attendances_batch_source"
        ),
        schema="raw_attendance",
    )

    # -- staging: rebuilt-per-run working area --------------------------------
    op.create_table(
        "attendance_students",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("account_number", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "source_system", "source_id", name="uq_staging_attendance_students_source"
        ),
        sa.CheckConstraint(
            "length(trim(account_number)) > 0",
            name="ck_staging_attendance_students_account_number_not_empty",
        ),
        schema="staging",
    )

    op.create_table(
        "attendance_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "source_system", "source_id", name="uq_staging_attendance_sessions_source"
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'CLOSED')", name="ck_staging_attendance_sessions_status"
        ),
        schema="staging",
    )

    op.create_table(
        "attendance_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("student_source_id", sa.Text(), nullable=False),
        sa.Column("session_source_id", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_hash", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "source_system", "source_id", name="uq_staging_attendance_records_source"
        ),
        schema="staging",
    )


def downgrade() -> None:
    op.drop_table("attendance_records", schema="staging")
    op.drop_table("attendance_sessions", schema="staging")
    op.drop_table("attendance_students", schema="staging")
    op.drop_table("attendances", schema="raw_attendance")
    op.drop_table("sessions", schema="raw_attendance")
    op.drop_table("students", schema="raw_attendance")
    op.drop_table("attendance_record_sources", schema="integration")
    op.drop_table("attendance_session_sources", schema="integration")
    op.drop_table("attendance_records", schema="academic")
    op.drop_table("attendance_sessions", schema="academic")
