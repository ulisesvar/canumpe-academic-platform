"""weighted evaluation engine: academic.grade_categories,
academic.grade_item_evaluation

Revision ID: 0008_evaluation_engine
Revises: 0007_api_key_auth
Create Date: 2026-09-17

Phase 7: adds the Academic-Platform-owned evaluation configuration that
explains a student's current grade — course evaluation categories and
their weights, and the mapping from a canonical grade item to at most
one category (grade_item_id is this table's own primary key, so "at
most one category per item" is a structural guarantee, not just an
application check). Moodle remains authoritative for grade items and
recorded grades themselves; this migration never touches those tables'
data, and CANUMPE never writes evaluation configuration back to Moodle.

A single category's weight_percent is bounded to [0, 100] here; the
cross-row invariant "a course's categories total exactly 100%" cannot
be expressed as a single-row CHECK constraint (PostgreSQL CHECK can't
reference other rows) and is enforced instead in
app.services.evaluation_service before any write.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008_evaluation_engine"
down_revision: str | None = "0007_api_key_auth"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "grade_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "course_id",
            sa.Integer(),
            sa.ForeignKey("academic.courses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("weight_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "weight_percent >= 0", name="ck_grade_categories_weight_percent_nonneg"
        ),
        sa.CheckConstraint("weight_percent <= 100", name="ck_grade_categories_weight_percent_max"),
        sa.UniqueConstraint("course_id", "name", name="uq_grade_categories_course_name"),
        sa.UniqueConstraint(
            "course_id", "sort_order", name="uq_grade_categories_course_sort_order"
        ),
        schema="academic",
    )
    op.create_index(
        "ix_grade_categories_course_id", "grade_categories", ["course_id"], schema="academic"
    )

    op.create_table(
        "grade_item_evaluation",
        sa.Column(
            "grade_item_id",
            sa.Integer(),
            sa.ForeignKey("academic.grade_items.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("academic.grade_categories.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("counts_toward_current_grade", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        schema="academic",
    )
    op.create_index(
        "ix_grade_item_evaluation_category_id",
        "grade_item_evaluation",
        ["category_id"],
        schema="academic",
    )


def downgrade() -> None:
    op.drop_table("grade_item_evaluation", schema="academic")
    op.drop_table("grade_categories", schema="academic")
