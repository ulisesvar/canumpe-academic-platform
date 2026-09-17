"""grades ingestion: canonical grade tables, source mappings, raw_moodle
and staging tables

Revision ID: 0006_grades_ingestion
Revises: 0005_sync_issues
Create Date: 2026-09-17

Phase 4: adds academic.grade_items/student_grades, their
integration.*_sources mappings, and the raw_moodle.grade_items/
student_grades + staging.grade_items/student_grades tables used by the
Moodle grades ingestion pipeline. Only real module-backed activities
(Moodle itemtype='mod') are ever canonicalized here — the course total
and any category totals are excluded by the extraction query itself and
never reach any of these tables. Grades resolve their student and course
through the existing integration.student_sources/course_sources mappings
(source_system='moodle') — this migration never touches those tables'
data and creates no new mapping table for students.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_grades_ingestion"
down_revision: str | None = "0005_sync_issues"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # -- academic: canonical grade structures --------------------------------
    op.create_table(
        "grade_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "course_id",
            sa.Integer(),
            sa.ForeignKey("academic.courses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("max_grade", sa.Numeric(10, 5), nullable=False),
        sa.Column("activity_type", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        schema="academic",
    )
    op.create_index("ix_grade_items_course_id", "grade_items", ["course_id"], schema="academic")

    op.create_table(
        "student_grades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "grade_item_id",
            sa.Integer(),
            sa.ForeignKey("academic.grade_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            sa.Integer(),
            sa.ForeignKey("academic.students.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("grade", sa.Numeric(10, 5), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("grade_item_id", "student_id", name="uq_student_grades_item_student"),
        schema="academic",
    )
    op.create_index(
        "ix_student_grades_grade_item_id", "student_grades", ["grade_item_id"], schema="academic"
    )
    op.create_index(
        "ix_student_grades_student_id", "student_grades", ["student_id"], schema="academic"
    )

    # -- integration: source identity mappings -------------------------------
    op.create_table(
        "grade_item_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "grade_item_id",
            sa.Integer(),
            sa.ForeignKey("academic.grade_items.id", ondelete="RESTRICT"),
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
        sa.UniqueConstraint("source_system", "source_id", name="uq_grade_item_sources_source"),
        sa.CheckConstraint(
            "length(trim(source_system)) > 0",
            name="ck_grade_item_sources_source_system_not_empty",
        ),
        sa.CheckConstraint(
            "length(trim(source_id)) > 0", name="ck_grade_item_sources_source_id_not_empty"
        ),
        schema="integration",
    )
    op.create_index(
        "ix_grade_item_sources_grade_item_id",
        "grade_item_sources",
        ["grade_item_id"],
        schema="integration",
    )

    op.create_table(
        "student_grade_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "student_grade_id",
            sa.Integer(),
            sa.ForeignKey("academic.student_grades.id", ondelete="RESTRICT"),
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
            "source_system", "source_id", name="uq_student_grade_sources_source"
        ),
        sa.CheckConstraint(
            "length(trim(source_system)) > 0",
            name="ck_student_grade_sources_source_system_not_empty",
        ),
        sa.CheckConstraint(
            "length(trim(source_id)) > 0", name="ck_student_grade_sources_source_id_not_empty"
        ),
        schema="integration",
    )
    op.create_index(
        "ix_student_grade_sources_student_grade_id",
        "student_grade_sources",
        ["student_grade_id"],
        schema="integration",
    )

    # -- raw_moodle: faithful, append-only landing copies ---------------------
    op.create_table(
        "grade_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("course_source_id", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("itemmodule", sa.Text(), nullable=True),
        sa.Column("max_grade", sa.Numeric(10, 5), nullable=True),
        sa.Column("hidden", sa.Boolean(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_hash", sa.Text(), nullable=False),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "batch_id", "source_id", name="uq_raw_moodle_grade_items_batch_source"
        ),
        schema="raw_moodle",
    )

    op.create_table(
        "student_grades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("grade_item_source_id", sa.Text(), nullable=True),
        sa.Column("student_source_id", sa.Text(), nullable=True),
        sa.Column("grade", sa.Numeric(10, 5), nullable=True),
        sa.Column("hidden", sa.Boolean(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_hash", sa.Text(), nullable=False),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "batch_id", "source_id", name="uq_raw_moodle_student_grades_batch_source"
        ),
        schema="raw_moodle",
    )

    # -- staging: rebuilt-per-run working area --------------------------------
    op.create_table(
        "grade_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("course_source_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("itemmodule", sa.Text(), nullable=True),
        sa.Column("max_grade", sa.Numeric(10, 5), nullable=False),
        sa.Column("source_hash", sa.Text(), nullable=False),
        sa.UniqueConstraint("source_system", "source_id", name="uq_staging_grade_items_source"),
        sa.CheckConstraint(
            "length(trim(name)) > 0", name="ck_staging_grade_items_name_not_empty"
        ),
        sa.CheckConstraint("max_grade > 0", name="ck_staging_grade_items_max_grade_positive"),
        schema="staging",
    )

    op.create_table(
        "student_grades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("grade_item_source_id", sa.Text(), nullable=False),
        sa.Column("student_source_id", sa.Text(), nullable=False),
        sa.Column("grade", sa.Numeric(10, 5), nullable=True),
        sa.Column("source_hash", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "source_system", "source_id", name="uq_staging_student_grades_source"
        ),
        schema="staging",
    )


def downgrade() -> None:
    op.drop_table("student_grades", schema="staging")
    op.drop_table("grade_items", schema="staging")
    op.drop_table("student_grades", schema="raw_moodle")
    op.drop_table("grade_items", schema="raw_moodle")
    op.drop_table("student_grade_sources", schema="integration")
    op.drop_table("grade_item_sources", schema="integration")
    op.drop_table("student_grades", schema="academic")
    op.drop_table("grade_items", schema="academic")
