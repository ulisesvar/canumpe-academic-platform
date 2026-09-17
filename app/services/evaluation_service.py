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

Precision discipline: every intermediate value (category score,
contribution, weighted points, evaluated weight, current score/grade)
stays a full-precision Decimal until the very last step — the
`_round2` calls that build the Pydantic response objects. Nothing here
is rounded and then fed back into further arithmetic.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

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
from app.repositories import student_read_repository as student_repo
from app.services.grade_normalization import normalize_score, round2, round2_or_none
from app.services.student_read_service import StudentNotFoundError

_HUNDRED = Decimal(100)


class NoEvaluableCourseError(Exception):
    """Raised by GET /me/evaluation when course_id is omitted and the
    student isn't enrolled in exactly one course to default to.
    """

    def __init__(self, student_id: int) -> None:
        self.student_id = student_id
        super().__init__(f"student_id={student_id!r} has no single enrolled course to evaluate")


class CourseNotFoundError(Exception):
    """Raised when a course_id used in an evaluation-scheme request doesn't exist."""

    def __init__(self, course_id: int) -> None:
        self.course_id = course_id
        super().__init__(f"course_id={course_id!r} does not exist")


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


def _build_fact(row: RowMapping) -> _ItemFact:
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


def get_student_evaluation(
    db: Session, student_id: int, course_id: int | None
) -> StudentEvaluationResponse:
    if not student_repo.student_exists(db, student_id):
        raise StudentNotFoundError(student_id)

    resolved_course_id = _resolve_course_id(db, student_id, course_id)

    category_rows = repo.list_categories_for_course(db, resolved_course_id)
    item_rows = repo.list_evaluation_items_for_student_course(db, student_id, resolved_course_id)

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
        course_id=resolved_course_id,
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
