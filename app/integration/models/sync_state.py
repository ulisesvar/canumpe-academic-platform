from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SyncState(Base):
    """Last successfully committed synchronization cursor/watermark.

    Must only ever reflect processing that has already been committed to
    the academic schema — never advanced speculatively before a merge
    succeeds.

    updated_at defaults on insert but has no `onupdate` default: the
    watermark advance is exactly the kind of pipeline write (a PostgreSQL
    upsert, or a plain UPDATE issued by sync code) that must not rely on
    ORM/Core `onupdate` — the future sync implementation must set
    updated_at explicitly, in the same write that advances `state`.
    """

    __tablename__ = "sync_state"
    __table_args__ = (
        UniqueConstraint("source_system", "entity_type", name="uq_sync_state_source_entity"),
        CheckConstraint(
            "length(trim(source_system)) > 0", name="ck_sync_state_source_system_not_empty"
        ),
        CheckConstraint(
            "length(trim(entity_type)) > 0", name="ck_sync_state_entity_type_not_empty"
        ),
        {"schema": "integration"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_system: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
