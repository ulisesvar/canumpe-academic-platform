"""API key authentication: auth.api_keys

Revision ID: 0007_api_key_auth
Revises: 0006_grades_ingestion
Create Date: 2026-09-17

Phase 6: adds auth.api_keys, the only table backing API-key
authentication/authorization. Only a SHA-256 hash of each key is ever
stored — never plaintext (see app.auth.api_keys). role is either
'student' (tied to exactly one academic.students row) or 'admin' (never
tied to a student); a CHECK constraint enforces that pairing at the
database level, not just in application code. A partial unique index
enforces at most one *active* (non-revoked) student key per student —
rotation is the supported way to replace one. auth was created empty in
0002_academic_data_foundation; this is its first table.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_api_key_auth"
down_revision: str | None = "0006_grades_ingestion"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column("key_prefix", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column(
            "student_id",
            sa.Integer(),
            sa.ForeignKey("academic.students.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("key_hash", name="uq_api_keys_key_hash"),
        sa.CheckConstraint("role IN ('student', 'admin')", name="ck_api_keys_role"),
        sa.CheckConstraint(
            "(role = 'student' AND student_id IS NOT NULL) OR "
            "(role = 'admin' AND student_id IS NULL)",
            name="ck_api_keys_role_student_id_consistency",
        ),
        schema="auth",
    )
    op.create_index("ix_api_keys_student_id", "api_keys", ["student_id"], schema="auth")
    # At most one active student key per student — rotation replaces it
    # rather than issuing a second one. Admin rows (student_id always
    # NULL) are naturally unaffected: PostgreSQL never treats two NULLs
    # as conflicting in a unique index.
    op.create_index(
        "uq_api_keys_active_student",
        "api_keys",
        ["student_id"],
        unique=True,
        schema="auth",
        postgresql_where=sa.text("role = 'student' AND revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("api_keys", schema="auth")
