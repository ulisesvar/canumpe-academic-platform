"""The weighted evaluation engine — explains a student's current grade
from canonical grade items grouped into instructor-configured
categories. See the README's evaluation-engine section for the full
worked example and formulas this module implements.

Normalization: score_100 = (grade / max_grade) * 100 (normalize_score
below) — computed once per fact and reused by both the enriched
/me/grades response (app.services.student_read_service) and the
evaluation breakdown here, so the formula is never duplicated. A NULL
grade, or a non-positive max_grade, both normalize to score_100=None —
never a divide-by-zero, never an invented number.

Category score: an equal-weight average of score_100 across a
category's currently-counted, actually-graded items only (Phase 7 does
not model per-item weights within a category). A category with zero
graded-and-counted items is not currently calculable for that student —
it contributes nothing, and its weight is excluded from
evaluated_weight, rather than a zero being invented for it.

Attendance/participation category (Phase 8.3): a category whose
calculation_type is ATTENDANCE_PARTICIPATION has no grade items; its
category score is instead

    attendance_score_100 * 0.33 + participation_score_100 * 0.67

built from app.services.attendance_score_service (Phase 8.2) and
app.services.participation_service (Phase 8.1) — neither formula is
repeated here. If either component is None (no CLOSED sessions / no
participation observations) the category score is None, never a
substituted zero (a real 0 in either component is a real zero), and the
category is then excluded from evaluated weight exactly like an
item-based category with nothing graded. The strategy is chosen by the
category's explicit calculation_type, never by its name.

Precision discipline: every intermediate value (category score,
contribution, weighted points, evaluated weight, current score/grade)
stays a full-precision Decimal until the very last step — the
`_round2` calls that build the Pydantic response objects. Nothing here
is rounded and then fed back into further arithmetic.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.academic.models.grade_category import CALCULATION_ATTENDANCE_PARTICIPATION
from app.api.schemas.evaluation import (
    CategoryEvaluation,
    EvaluationItem,
    StudentEvaluationResponse,
)
from app.api.schemas.evaluation_scheme import (
    CategoryScheme,
    EvaluationSchemeRequest,
    EvaluationSchemeResponse,
    GradeItemAssignment,
    UnassignedGradeItem,
)
from app.repositories import evaluation_repository as repo
from app.repositories import participation_repository
from app.repositories import student_read_repository as student_repo
from app.services.attendance_score_service import get_attendance_score
from app.services.errors import CourseNotFoundError
from app.services.grade_normalization import normalize_score, round2, round2_or_none
from app.services.participation_service import summarize_participation
from app.services.student_read_service import StudentNotFoundError

__all__ = ["CourseNotFoundError"]  # re-exported: defined in app.services.errors

_HUNDRED = Decimal(100)
# Internal split of the ATTENDANCE_PARTICIPATION strategy — belongs to the
# strategy, not to any course's configuration (the category's own weight
# is configuration: GradeCategory.weight_percent).
ATTENDANCE_WEIGHT = Decimal("0.33")
PARTICIPATION_WEIGHT = Decimal("0.67")


class NoEvaluableCourseError(Exception):
    """Raised by GET /me/evaluation when course_id is omitted and the
    student isn't enrolled in exactly one course to default to.
    """

    def __init__(self, student_id: int) -> None:
        self.student_id = student_id
        super().__init__(f"student_id={student_id!r} has no single enrolled course to evaluate")


class InvalidEvaluationSchemeError(Exception):
    """Raised when a PUT evaluation-scheme payload fails validation —
    always before any write, so an invalid payload changes nothing.
    """


@dataclass(frozen=True)
class _ItemFact:
    grade_item_id: int
    name: str
    activity_type: str | None
    max_grade: Decimal
    counts_toward_current_grade: bool
    grade: Decimal | None
    score_100: Decimal | None


def _build_fact(row: Mapping[Any, Any]) -> _ItemFact:
    grade = row["grade"]
    max_grade = row["max_grade"]
    return _ItemFact(
        grade_item_id=row["grade_item_id"],
        name=row["name"],
        activity_type=row["activity_type"],
        max_grade=max_grade,
        counts_toward_current_grade=row["counts_toward_current_grade"],
        grade=grade,
        score_100=normalize_score(grade, max_grade),
    )


def _resolve_course_id(db: Session, student_id: int, course_id: int | None) -> int:
    if course_id is not None:
        return course_id
    enrolled = student_repo.list_enrolled_courses(db, student_id)
    if len(enrolled) != 1:
        raise NoEvaluableCourseError(student_id)
    return int(enrolled[0]["id"])


def blend_attendance_participation(
    attendance_score_100: Decimal | None, participation_score_100: Decimal | None
) -> Decimal | None:
    """The ATTENDANCE_PARTICIPATION category score: None unless BOTH
    components exist — a missing component is never replaced by zero.
    Real zeros in either component are used as zeros.
    """
    if attendance_score_100 is None or participation_score_100 is None:
        return None
    return attendance_score_100 * ATTENDANCE_WEIGHT + participation_score_100 * PARTICIPATION_WEIGHT


def _attendance_participation_score_100(
    db: Session, student_id: int, course_id: int
) -> Decimal | None:
    attendance_score_100 = get_attendance_score(db, student_id, course_id).score_100
    observations = participation_repository.list_observations(db, course_id, student_id)
    participation_score_100 = summarize_participation(
        [row["value"] for row in observations]
    ).score_100
    return blend_attendance_participation(attendance_score_100, participation_score_100)


def get_student_evaluation(
    db: Session, student_id: int, course_id: int | None
) -> StudentEvaluationResponse:
    if not student_repo.student_exists(db, student_id):
        raise StudentNotFoundError(student_id)

    resolved_course_id = _resolve_course_id(db, student_id, course_id)

    category_rows = repo.list_categories_for_course(db, resolved_course_id)
    item_rows = repo.list_evaluation_items_for_student_course(db, student_id, resolved_course_id)

    # Only a course that has an attendance/participation category needs its
    # attendance and participation data loaded.
    attendance_participation_score_100 = (
        _attendance_participation_score_100(db, student_id, resolved_course_id)
        if any(
            row["calculation_type"] == CALCULATION_ATTENDANCE_PARTICIPATION for row in category_rows
        )
        else None
    )

    return calculate_student_evaluation(
        student_id,
        resolved_course_id,
        category_rows,
        item_rows,
        attendance_participation_score_100,
    )


def calculate_student_evaluation(
    student_id: int,
    course_id: int,
    category_rows: Sequence[Mapping[Any, Any]],
    item_rows: Sequence[Mapping[Any, Any]],
    attendance_participation_score_100: Decimal | None,
) -> StudentEvaluationResponse:
    """The pure evaluation calculation — no database access. Shared by
    get_student_evaluation (one student) and the course gradebook
    (app.services.gradebook_service, every student from bulk-loaded
    data), so both always produce identical numbers.

    category_rows: {id, name, weight_percent, calculation_type}, ordered
    by sort_order. item_rows: {category_id, grade_item_id, name,
    activity_type, max_grade, counts_toward_current_grade, grade} — one
    row per configured item for THIS student (grade None when they have
    no grade), ordered by item id. attendance_participation_score_100 is
    the already-blended ATTENDANCE_PARTICIPATION score (None if either
    component is missing); it is ignored when there is no such category.
    """
    facts_by_category: dict[int, list[_ItemFact]] = {}
    for row in item_rows:
        facts_by_category.setdefault(row["category_id"], []).append(_build_fact(row))

    categories: list[CategoryEvaluation] = []
    weighted_points_earned = Decimal(0)
    evaluated_weight = Decimal(0)

    for category_row in category_rows:
        facts = facts_by_category.get(category_row["id"], [])
        counted = [f for f in facts if f.counts_toward_current_grade]
        graded_counted = [f for f in counted if f.grade is not None]
        ungraded_counted = [f for f in counted if f.grade is None]

        category_score_100: Decimal | None
        if category_row["calculation_type"] == CALCULATION_ATTENDANCE_PARTICIPATION:
            category_score_100 = attendance_participation_score_100
        else:
            valid_scores = [f.score_100 for f in graded_counted if f.score_100 is not None]
            category_score_100 = (
                sum(valid_scores, Decimal(0)) / len(valid_scores) if valid_scores else None
            )

        weight_percent: Decimal = category_row["weight_percent"]
        contribution: Decimal | None
        if category_score_100 is not None:
            contribution = category_score_100 * weight_percent / _HUNDRED
            weighted_points_earned += contribution
            evaluated_weight += weight_percent
        else:
            contribution = None

        categories.append(
            CategoryEvaluation(
                category_id=category_row["id"],
                name=category_row["name"],
                weight_percent=round2(weight_percent),
                category_score_100=round2_or_none(category_score_100),
                contribution_points=round2_or_none(contribution),
                counted_items=len(counted),
                graded_items=len(graded_counted),
                ungraded_items=len(ungraded_counted),
                items=[
                    EvaluationItem(
                        grade_item_id=f.grade_item_id,
                        name=f.name,
                        activity_type=f.activity_type,
                        grade=float(f.grade) if f.grade is not None else None,
                        max_grade=float(f.max_grade),
                        score_100=round2_or_none(f.score_100),
                        counts_toward_current_grade=f.counts_toward_current_grade,
                    )
                    for f in facts
                ],
            )
        )

    current_score_100: Decimal | None
    current_grade_10: Decimal | None
    if evaluated_weight > 0:
        score_100 = weighted_points_earned / evaluated_weight * _HUNDRED
        current_score_100 = score_100
        current_grade_10 = score_100 / Decimal(10)
    else:
        current_score_100 = None
        current_grade_10 = None

    return StudentEvaluationResponse(
        student_id=student_id,
        course_id=course_id,
        weighted_points_earned=round2(weighted_points_earned),
        evaluated_weight_percent=round2(evaluated_weight),
        current_score_100=round2_or_none(current_score_100),
        current_grade_10=round2_or_none(current_grade_10),
        categories=categories,
    )


def get_evaluation_scheme(db: Session, course_id: int) -> EvaluationSchemeResponse:
    course = repo.get_course(db, course_id)
    if course is None:
        raise CourseNotFoundError(course_id)

    category_rows = repo.list_categories_for_course(db, course_id)
    assignment_rows = repo.list_all_grade_item_assignments_for_course(db, course_id)
    unassigned_rows = repo.list_unassigned_grade_items_for_course(db, course_id)

    assignments_by_category: dict[int, list[GradeItemAssignment]] = {}
    for row in assignment_rows:
        assignments_by_category.setdefault(row["category_id"], []).append(
            GradeItemAssignment(
                grade_item_id=row["grade_item_id"],
                name=row["name"],
                activity_type=row["activity_type"],
                counts_toward_current_grade=row["counts_toward_current_grade"],
            )
        )

    categories = [
        CategoryScheme(
            category_id=row["id"],
            name=row["name"],
            weight_percent=float(row["weight_percent"]),
            sort_order=row["sort_order"],
            calculation_type=row["calculation_type"],
            grade_items=assignments_by_category.get(row["id"], []),
        )
        for row in category_rows
    ]

    unassigned = [
        UnassignedGradeItem(
            grade_item_id=row["id"], name=row["name"], activity_type=row["activity_type"]
        )
        for row in unassigned_rows
    ]

    return EvaluationSchemeResponse(
        course_id=course_id,
        course_name=course["name"],
        categories=categories,
        unassigned_grade_items=unassigned,
    )


def _validate_evaluation_scheme(
    db: Session, course_id: int, payload: EvaluationSchemeRequest
) -> None:
    total_weight = sum((c.weight_percent for c in payload.categories), Decimal(0))
    if total_weight != _HUNDRED:
        raise InvalidEvaluationSchemeError(
            f"category weights must total exactly 100, got {total_weight}"
        )

    names = [c.name for c in payload.categories]
    if len(names) != len(set(names)):
        raise InvalidEvaluationSchemeError("duplicate category name in payload")

    sort_orders = [c.sort_order for c in payload.categories]
    if len(sort_orders) != len(set(sort_orders)):
        raise InvalidEvaluationSchemeError("duplicate sort_order in payload")

    attendance_participation_categories = [
        c for c in payload.categories if c.calculation_type == CALCULATION_ATTENDANCE_PARTICIPATION
    ]
    if len(attendance_participation_categories) > 1:
        raise InvalidEvaluationSchemeError(
            "at most one ATTENDANCE_PARTICIPATION category is allowed per course"
        )
    if any(c.grade_items for c in attendance_participation_categories):
        raise InvalidEvaluationSchemeError(
            "an ATTENDANCE_PARTICIPATION category cannot contain grade items"
        )
    if (
        not attendance_participation_categories
        and repo.course_has_attendance_participation_category(db, course_id)
    ):
        # The PUT deletes and recreates every category, so a payload that
        # omits it would silently destroy the course's existing
        # attendance/participation category (e.g. a Phase 7 client that
        # never sends calculation_type). Deliberate removal isn't supported.
        raise InvalidEvaluationSchemeError(
            "this course has an ATTENDANCE_PARTICIPATION category; the replacement scheme "
            "must include one (calculation_type=ATTENDANCE_PARTICIPATION) — removing it is "
            "not supported"
        )

    all_grade_item_ids = [
        item.grade_item_id for category in payload.categories for item in category.grade_items
    ]
    if len(all_grade_item_ids) != len(set(all_grade_item_ids)):
        raise InvalidEvaluationSchemeError(
            "a grade item cannot be assigned to more than one category"
        )

    if all_grade_item_ids:
        item_courses = repo.get_grade_item_courses(db, all_grade_item_ids)
        missing = sorted(set(all_grade_item_ids) - set(item_courses))
        if missing:
            raise InvalidEvaluationSchemeError(f"unknown grade_item_id(s): {missing}")

        wrong_course = sorted(gid for gid, cid in item_courses.items() if cid != course_id)
        if wrong_course:
            raise InvalidEvaluationSchemeError(
                f"grade_item_id(s) {wrong_course} do not belong to course_id={course_id!r}"
            )


def replace_evaluation_scheme(
    db: Session, course_id: int, payload: EvaluationSchemeRequest
) -> EvaluationSchemeResponse:
    if not repo.course_exists(db, course_id):
        raise CourseNotFoundError(course_id)

    _validate_evaluation_scheme(db, course_id, payload)

    repo.replace_course_evaluation_scheme(db, course_id, payload)
    db.commit()

    return get_evaluation_scheme(db, course_id)
