"""moodle ingestion: raw_moodle and staging tables

Revision ID: 0003_moodle_ingestion
Revises: 0002_academic_data_foundation
Create Date: 2026-09-16

Phase 2: adds the raw_moodle.* landing tables and the staging.* working
tables used by the Moodle ingestion pipeline. academic.* and
integration.* already exist from Phase 1 and are unchanged — this
migration only adds new tables in already-existing schemas.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_moodle_ingestion"
down_revision: str | None = "0002_academic_data_foundation"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # -- raw_moodle: faithful, append-only landing copies -------------------
    op.create_table(
        "students",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("account_number", sa.Text(), nullable=True),
        sa.Column("first_name", sa.Text(), nullable=True),
        sa.Column("last_name", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_hash", sa.Text(), nullable=False),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("batch_id", "source_id", name="uq_raw_moodle_students_batch_source"),
        schema="raw_moodle",
    )

    op.create_table(
        "courses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("visible", sa.Boolean(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_hash", sa.Text(), nullable=False),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("batch_id", "source_id", name="uq_raw_moodle_courses_batch_source"),
        schema="raw_moodle",
    )

    op.create_table(
        "enrollments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("student_source_id", sa.Text(), nullable=True),
        sa.Column("course_source_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_hash", sa.Text(), nullable=False),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("batch_id", "source_id", name="uq_raw_moodle_enrollments_batch_source"),
        sa.CheckConstraint(
            "length(trim(source_id)) > 0", name="ck_raw_moodle_enrollments_source_id_not_empty"
        ),
        schema="raw_moodle",
    )

    # -- staging: rebuilt-per-run working area -------------------------------
    op.create_table(
        "students",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("account_number", sa.Text(), nullable=False),
        sa.Column("first_name", sa.Text(), nullable=False),
        sa.Column("last_name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_hash", sa.Text(), nullable=False),
        sa.UniqueConstraint("source_system", "source_id", name="uq_staging_students_source"),
        sa.CheckConstraint(
            "length(trim(account_number)) > 0", name="ck_staging_students_account_number_not_empty"
        ),
        schema="staging",
    )

    op.create_table(
        "courses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_hash", sa.Text(), nullable=False),
        sa.UniqueConstraint("source_system", "source_id", name="uq_staging_courses_source"),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_staging_courses_name_not_empty"),
        schema="staging",
    )

    op.create_table(
        "enrollments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("student_source_id", sa.Text(), nullable=False),
        sa.Column("course_source_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_hash", sa.Text(), nullable=False),
        sa.UniqueConstraint("source_system", "source_id", name="uq_staging_enrollments_source"),
        schema="staging",
    )


def downgrade() -> None:
    op.drop_table("enrollments", schema="staging")
    op.drop_table("courses", schema="staging")
    op.drop_table("students", schema="staging")
    op.drop_table("enrollments", schema="raw_moodle")
    op.drop_table("courses", schema="raw_moodle")
    op.drop_table("students", schema="raw_moodle")
