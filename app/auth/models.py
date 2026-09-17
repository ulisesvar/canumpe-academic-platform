from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

ROLE_STUDENT = "student"
ROLE_ADMIN = "admin"
API_KEY_ROLES = (ROLE_STUDENT, ROLE_ADMIN)


class ApiKey(Base):
    """One issued API-key credential. Never holds a plaintext key —
    key_hash is SHA-256(plaintext); key_prefix is a short, non-secret
    slice of the plaintext kept only for administrative identification
    (see app.auth.api_keys). role='student' rows always reference the
    one canonical student the key authenticates as; role='admin' rows
    are never tied to a student — both enforced by
    ck_api_keys_role_student_id_consistency, not just application code.

    revoked_at is set explicitly by app.auth.api_keys.revoke_key — never
    an ORM/Core `onupdate`, no triggers, same invariant as everywhere
    else in this platform. Rows are never deleted, so revoked
    credentials remain as permanent history.
    """

    __tablename__ = "api_keys"
    __table_args__ = (
        UniqueConstraint("key_hash", name="uq_api_keys_key_hash"),
        CheckConstraint("role IN ('student', 'admin')", name="ck_api_keys_role"),
        CheckConstraint(
            "(role = 'student' AND student_id IS NOT NULL) OR "
            "(role = 'admin' AND student_id IS NULL)",
            name="ck_api_keys_role_student_id_consistency",
        ),
        Index("ix_api_keys_student_id", "student_id"),
        Index(
            "uq_api_keys_active_student",
            "student_id",
            unique=True,
            postgresql_where=text("role = 'student' AND revoked_at IS NULL"),
        ),
        {"schema": "auth"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    key_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("academic.students.id", ondelete="RESTRICT"), nullable=True
    )
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
