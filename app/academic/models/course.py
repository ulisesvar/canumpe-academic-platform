from sqlalchemy import Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Course(TimestampMixin, Base):
    """Canonical academic course.

    The Moodle course id is not assumed to be the canonical id — source
    identity is tracked separately in app.integration.models.course_source.
    """

    __tablename__ = "courses"
    __table_args__ = {"schema": "academic"}

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
