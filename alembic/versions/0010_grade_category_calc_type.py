"""grade category calculation type: academic.grade_categories.calculation_type

Revision ID: 0010_grade_category_calc_type
Revises: 0009_participation_observations
Create Date: 2026-09-29

(The revision id is deliberately short: alembic_version.version_num is
varchar(32), and "0010_grade_category_calculation_type" is 36 characters.)

Phase 8.3: adds an explicit calculation_type to a course's evaluation
categories, so one category can be scored by the attendance/
participation strategy instead of from grade items. The strategy is
never inferred from a category's name.

Every existing row is backfilled to 'GRADE_ITEMS' by the column's
server default (existing Phase 7 behavior, unchanged). The allowed
values are constrained by a CHECK. A partial unique index guarantees at
most one 'ATTENDANCE_PARTICIPATION' category per course at the
database level (a course's other categories are unconstrained), backing
the same rule the API validates before any write.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010_grade_category_calc_type"
down_revision: str | None = "0009_participation_observations"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "grade_categories",
        sa.Column(
            "calculation_type",
            sa.Text(),
            nullable=False,
            server_default="GRADE_ITEMS",
        ),
        schema="academic",
    )
    op.create_check_constraint(
        "ck_grade_categories_calculation_type",
        "grade_categories",
        "calculation_type IN ('GRADE_ITEMS', 'ATTENDANCE_PARTICIPATION')",
        schema="academic",
    )
    op.create_index(
        "uq_grade_categories_course_attendance_participation",
        "grade_categories",
        ["course_id"],
        unique=True,
        schema="academic",
        postgresql_where=sa.text("calculation_type = 'ATTENDANCE_PARTICIPATION'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_grade_categories_course_attendance_participation",
        table_name="grade_categories",
        schema="academic",
    )
    op.drop_constraint(
        "ck_grade_categories_calculation_type",
        "grade_categories",
        schema="academic",
        type_="check",
    )
    op.drop_column("grade_categories", "calculation_type", schema="academic")
