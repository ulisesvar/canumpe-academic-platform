"""bot API-key role: auth.api_keys.course_id and role 'bot'

Revision ID: 0012_bot_api_key_role
Revises: 0011_category_moodle_activity
Create Date: 2026-10-04

Adds a third credential role, 'bot', for a server-to-server client (the
Telegram attendance bot) that may read ONE student's evaluation for ONE
course and nothing else. A bot key is tied to a course, never to a
student, so auth.api_keys gains a nullable course_id (FK to
academic.courses) and the role/identity CHECK constraint now pairs each
role with exactly the columns it may carry:

    student: student_id NOT NULL, course_id NULL
    admin:   student_id NULL,     course_id NULL
    bot:     student_id NULL,     course_id NOT NULL

Existing rows are untouched: every current row is a student or admin key
with course_id NULL, so it satisfies the new constraints as-is. No key
hash is altered and nothing is revoked. The partial unique index
uq_api_keys_active_student is unaffected (it only covers role='student').

Downgrade deletes the bot key rows first: the older schema cannot represent
them (no course_id, role not allowed), exactly as downgrading 0007 drops the
whole table. Student and admin keys are left untouched.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012_bot_api_key_role"
down_revision: str | None = "0011_category_moodle_activity"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column(
            "course_id",
            sa.Integer(),
            sa.ForeignKey("academic.courses.id", ondelete="RESTRICT", name="fk_api_keys_course_id"),
            nullable=True,
        ),
        schema="auth",
    )
    op.create_index("ix_api_keys_course_id", "api_keys", ["course_id"], schema="auth")

    op.drop_constraint("ck_api_keys_role", "api_keys", schema="auth", type_="check")
    op.drop_constraint(
        "ck_api_keys_role_student_id_consistency", "api_keys", schema="auth", type_="check"
    )
    op.create_check_constraint(
        "ck_api_keys_role",
        "api_keys",
        "role IN ('student', 'admin', 'bot')",
        schema="auth",
    )
    op.create_check_constraint(
        "ck_api_keys_role_student_id_consistency",
        "api_keys",
        "(role = 'student' AND student_id IS NOT NULL AND course_id IS NULL) OR "
        "(role = 'admin' AND student_id IS NULL AND course_id IS NULL) OR "
        "(role = 'bot' AND student_id IS NULL AND course_id IS NOT NULL)",
        schema="auth",
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM auth.api_keys WHERE role = 'bot'"))

    op.drop_constraint(
        "ck_api_keys_role_student_id_consistency", "api_keys", schema="auth", type_="check"
    )
    op.drop_constraint("ck_api_keys_role", "api_keys", schema="auth", type_="check")
    op.create_check_constraint(
        "ck_api_keys_role", "api_keys", "role IN ('student', 'admin')", schema="auth"
    )
    op.create_check_constraint(
        "ck_api_keys_role_student_id_consistency",
        "api_keys",
        "(role = 'student' AND student_id IS NOT NULL) OR "
        "(role = 'admin' AND student_id IS NULL)",
        schema="auth",
    )
    op.drop_index("ix_api_keys_course_id", table_name="api_keys", schema="auth")
    op.drop_column("api_keys", "course_id", schema="auth")
