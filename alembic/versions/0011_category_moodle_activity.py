"""grade category Moodle activity mapping:
academic.grade_categories.moodle_activity_type

Revision ID: 0011_category_moodle_activity
Revises: 0010_grade_category_calc_type
Create Date: 2026-10-01

Adds the explicit link between a Moodle activity type (itemmodule, e.g.
'assign', 'quiz') and the evaluation category its grade items belong to,
so the Moodle sync can assign new grade items to a category automatically
(app.integration.moodle.grades_merge). The mapping is configuration on the
category, never inferred from a category's name or id afterwards.

moodle_activity_type is nullable (NULL = no automatic mapping, e.g. the
attendance/participation category) and unique per course: a Moodle
activity type maps to at most one category of a course. PostgreSQL allows
many NULLs in a UNIQUE constraint, which is what is wanted.

One-time backfill of the data that exists today: the categories named
"Entregables / tareas" and "Exámenes" (matched case-insensitively, within
GRADE_ITEMS categories only) are mapped to 'assign' and 'quiz'. The name is
used here, in this migration, ONLY to configure existing rows; every later
behavior reads moodle_activity_type exclusively. Names are unique per
course, so the backfill can never violate the new constraint. The
attendance/participation category is left NULL. No other data is touched.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011_category_moodle_activity"
down_revision: str | None = "0010_grade_category_calc_type"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# (name of an existing category today, Moodle activity type it maps to)
_BACKFILL = (
    ("Entregables / tareas", "assign"),
    ("Exámenes", "quiz"),
)


def upgrade() -> None:
    op.add_column(
        "grade_categories",
        sa.Column("moodle_activity_type", sa.Text(), nullable=True),
        schema="academic",
    )
    op.create_unique_constraint(
        "uq_grade_categories_course_moodle_activity_type",
        "grade_categories",
        ["course_id", "moodle_activity_type"],
        schema="academic",
    )

    for category_name, activity_type in _BACKFILL:
        op.execute(
            sa.text(
                """
                UPDATE academic.grade_categories
                SET moodle_activity_type = :activity_type, updated_at = now()
                WHERE moodle_activity_type IS NULL
                  AND calculation_type = 'GRADE_ITEMS'
                  AND lower(btrim(name)) = lower(:category_name)
                """
            ).bindparams(activity_type=activity_type, category_name=category_name)
        )


def downgrade() -> None:
    op.drop_constraint(
        "uq_grade_categories_course_moodle_activity_type",
        "grade_categories",
        schema="academic",
        type_="unique",
    )
    op.drop_column("grade_categories", "moodle_activity_type", schema="academic")
