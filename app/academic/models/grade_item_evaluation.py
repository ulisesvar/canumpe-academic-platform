from sqlalchemy import Boolean, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class GradeItemEvaluation(TimestampMixin, Base):
    """Maps one canonical grade item to at most one evaluation category.

    "At most one category per item" is structural, not an application
    check: grade_item_id is this table's own primary key (never a
    separate surrogate id + a unique constraint). counts_toward_current_grade
    is explicit configuration, set only by
    app.services.evaluation_service — never inferred from due dates,
    the current date, or grade presence (see the README's evaluation
    engine section).
    """

    __tablename__ = "grade_item_evaluation"
    __table_args__ = (
        Index("ix_grade_item_evaluation_category_id", "category_id"),
        {"schema": "academic"},
    )

    grade_item_id: Mapped[int] = mapped_column(
        ForeignKey("academic.grade_items.id", ondelete="RESTRICT"), primary_key=True
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("academic.grade_categories.id", ondelete="RESTRICT"), nullable=False
    )
    counts_toward_current_grade: Mapped[bool] = mapped_column(Boolean, nullable=False)
