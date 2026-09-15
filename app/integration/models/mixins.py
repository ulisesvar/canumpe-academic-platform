from datetime import datetime

from sqlalchemy import DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column


class SourceMappingMixin:
    """Shared columns for integration.*_sources mapping tables.

    Ties one canonical academic record to one identity in one source
    system. A canonical record may have multiple rows here (one per
    source system).

    first_seen_at defaults on insert. last_seen_at also defaults on insert,
    but deliberately has no `onupdate` default: a future synchronization
    pass that re-observes this mapping (an UPDATE or a PostgreSQL
    ON CONFLICT DO UPDATE upsert) must set last_seen_at explicitly. Do not
    assume touching this row advances last_seen_at on its own.
    """

    id: Mapped[int] = mapped_column(primary_key=True)
    source_system: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
