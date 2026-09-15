from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class TimestampMixin:
    """created_at/updated_at columns shared by canonical academic tables.

    created_at gets a DB default on insert. updated_at also defaults on
    insert (so it starts equal to created_at), but is deliberately NOT
    maintained via an ORM/Core `onupdate` default: pipeline correctness for
    UPDATE/UPSERT paths (bulk operations, Core statements, PostgreSQL
    ON CONFLICT DO UPDATE) must not depend on that mechanism, since it is
    silently skipped by upserts and some bulk/Core execution paths. Callers
    that mutate a row — including future synchronization logic — must set
    updated_at explicitly.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
