"""participation observations: academic.participation_observations

Revision ID: 0009_participation_observations
Revises: 0008_evaluation_engine
Create Date: 2026-09-29

Phase 8.1: adds the only persistence needed to record participation —
one row per manual observation of a student in a course, valued 0, 1,
2 or 3. A value of 0 is a real zero. Neither the average nor a 0-100
score is ever stored: both are derived from these rows at read time
(app.services.participation_service), so deleting a mistaken
observation can never leave a stale aggregate behind.

(student_id, course_id) is a composite foreign key to
academic.enrollments (via uq_enrollments_student_course), so the
database itself guarantees an observation can only exist for a student
enrolled in that course — not just an application check. Observations
are individually deletable; nothing references them.

recorded_by_api_key_id is nullable traceability only (which admin key
recorded the observation). This migration alters no existing table.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009_participation_observations"
down_revision: str | None = "0008_evaluation_engine"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "participation_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("value", sa.SmallInteger(), nullable=False),
        sa.Column(
            "observed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "recorded_by_api_key_id",
            sa.Integer(),
            sa.ForeignKey("auth.api_keys.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("value IN (0, 1, 2, 3)", name="ck_participation_observations_value"),
        sa.ForeignKeyConstraint(
            ["student_id", "course_id"],
            ["academic.enrollments.student_id", "academic.enrollments.course_id"],
            name="fk_participation_observations_enrollment",
            ondelete="RESTRICT",
        ),
        schema="academic",
    )
    op.create_index(
        "ix_participation_observations_course_student",
        "participation_observations",
        ["course_id", "student_id"],
        schema="academic",
    )


def downgrade() -> None:
    op.drop_table("participation_observations", schema="academic")
