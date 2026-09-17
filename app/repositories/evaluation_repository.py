"""Explicit, read-only queries backing the Phase 7 evaluation engine,
plus the write path for replacing a course's evaluation scheme.

Never touches Moodle/Attendance or their raw_*/staging landing tables —
only academic.* — and never contains calculation policy (category
averages, contributions, weighted grades): that lives entirely in
app.services.evaluation_service. This module answers "what rows match",
never "what does this number mean."
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import delete, insert, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from app.academic.models import (
    Course,
    GradeCategory,
    GradeItem,
    GradeItemEvaluation,
    StudentGrade,
)
from app.api.schemas.evaluation_scheme import EvaluationSchemeRequest


def course_exists(db: Session, course_id: int) -> bool:
    return (
        db.execute(select(Course.id).where(Course.id == course_id)).scalar_one_or_none()
        is not None
    )


def get_course(db: Session, course_id: int) -> RowMapping | None:
    return (
        db.execute(select(Course.id, Course.name).where(Course.id == course_id))
        .mappings()
        .one_or_none()
    )


def get_grade_item_courses(db: Session, grade_item_ids: Sequence[int]) -> dict[int, int]:
    """Maps grade_item_id -> course_id for exactly the given ids — used
    to validate a PUT payload's grade item references before any write.
    """
    if not grade_item_ids:
        return {}
    rows = db.execute(
        select(GradeItem.id, GradeItem.course_id).where(GradeItem.id.in_(grade_item_ids))
    ).all()
    return {row.id: row.course_id for row in rows}


def list_categories_for_course(db: Session, course_id: int) -> Sequence[RowMapping]:
    stmt = (
        select(
            GradeCategory.id,
            GradeCategory.name,
            GradeCategory.weight_percent,
            GradeCategory.sort_order,
        )
        .where(GradeCategory.course_id == course_id)
        .order_by(GradeCategory.sort_order, GradeCategory.id)
    )
    return db.execute(stmt).mappings().all()


def list_all_grade_item_assignments_for_course(db: Session, course_id: int) -> Sequence[RowMapping]:
    """One row per grade item configured (via grade_item_evaluation) for
    this course — every category's assignments in one deterministically
    ordered list, grouped by the caller.
    """
    stmt = (
        select(
            GradeItemEvaluation.category_id,
            GradeItem.id.label("grade_item_id"),
            GradeItem.name,
            GradeItem.activity_type,
            GradeItemEvaluation.counts_toward_current_grade,
        )
        .select_from(GradeItemEvaluation)
        .join(GradeItem, GradeItem.id == GradeItemEvaluation.grade_item_id)
        .where(GradeItem.course_id == course_id)
        .order_by(GradeItemEvaluation.category_id, GradeItem.id)
    )
    return db.execute(stmt).mappings().all()


def list_unassigned_grade_items_for_course(db: Session, course_id: int) -> Sequence[RowMapping]:
    stmt = (
        select(GradeItem.id, GradeItem.name, GradeItem.activity_type)
        .outerjoin(GradeItemEvaluation, GradeItemEvaluation.grade_item_id == GradeItem.id)
        .where(GradeItem.course_id == course_id, GradeItemEvaluation.grade_item_id.is_(None))
        .order_by(GradeItem.id)
    )
    return db.execute(stmt).mappings().all()


def list_evaluation_items_for_student_course(
    db: Session, student_id: int, course_id: int
) -> Sequence[RowMapping]:
    """One row per grade item configured for this course, left-joined to
    this specific student's grade (grade is None if they have no
    academic.student_grades row for it yet — never coerced).
    """
    stmt = (
        select(
            GradeItemEvaluation.category_id,
            GradeItem.id.label("grade_item_id"),
            GradeItem.name,
            GradeItem.activity_type,
            GradeItem.max_grade,
            GradeItemEvaluation.counts_toward_current_grade,
            StudentGrade.grade,
        )
        .select_from(GradeItemEvaluation)
        .join(GradeItem, GradeItem.id == GradeItemEvaluation.grade_item_id)
        .outerjoin(
            StudentGrade,
            (StudentGrade.grade_item_id == GradeItem.id)
            & (StudentGrade.student_id == student_id),
        )
        .where(GradeItem.course_id == course_id)
        .order_by(GradeItemEvaluation.category_id, GradeItem.id)
    )
    return db.execute(stmt).mappings().all()


def replace_course_evaluation_scheme(
    db: Session, course_id: int, payload: EvaluationSchemeRequest
) -> None:
    """Deletes this course's entire evaluation configuration and
    recreates it from the payload — the "atomic whole-scheme update"
    the API contract promises. Caller (app.services.evaluation_service)
    validates the payload first and commits after this returns; nothing
    here is committed on its own, so a failure partway through rolls
    back entirely when the session closes without a commit.
    """
    existing_category_ids = list(
        db.execute(
            select(GradeCategory.id).where(GradeCategory.course_id == course_id)
        ).scalars()
    )
    if existing_category_ids:
        db.execute(
            delete(GradeItemEvaluation).where(
                GradeItemEvaluation.category_id.in_(existing_category_ids)
            )
        )
        db.execute(delete(GradeCategory).where(GradeCategory.course_id == course_id))

    now = datetime.now(UTC)
    for category in payload.categories:
        new_category_id = db.execute(
            insert(GradeCategory)
            .values(
                course_id=course_id,
                name=category.name,
                weight_percent=category.weight_percent,
                sort_order=category.sort_order,
                updated_at=now,
            )
            .returning(GradeCategory.id)
        ).scalar_one()

        if category.grade_items:
            db.execute(
                insert(GradeItemEvaluation),
                [
                    {
                        "grade_item_id": item.grade_item_id,
                        "category_id": new_category_id,
                        "counts_toward_current_grade": item.counts_toward_current_grade,
                        "updated_at": now,
                    }
                    for item in category.grade_items
                ],
            )
