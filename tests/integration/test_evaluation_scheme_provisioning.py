"""Evaluation-scheme validation and atomic replace — see
app.services.evaluation_service.replace_evaluation_scheme. Uses the
SAVEPOINT-rollback db_session fixture: replace_evaluation_scheme calls
db.commit() internally, which the fixture is explicitly designed to
tolerate without ending the outer, rolled-back transaction.
"""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.academic.models import Course, GradeCategory, GradeItem, GradeItemEvaluation
from app.api.schemas.evaluation_scheme import (
    CategorySchemeRequest,
    EvaluationSchemeRequest,
    GradeItemAssignmentRequest,
)
from app.services.evaluation_service import (
    InvalidEvaluationSchemeError,
    get_evaluation_scheme,
    replace_evaluation_scheme,
)


def _course(db_session: Session, name: str = "Test Course") -> int:
    course = Course(name=name)
    db_session.add(course)
    db_session.commit()
    return course.id


def _grade_item(db_session: Session, course_id: int, name: str = "Item") -> int:
    item = GradeItem(course_id=course_id, name=name, max_grade=Decimal("100"))
    db_session.add(item)
    db_session.commit()
    return item.id


def _scheme(*categories: CategorySchemeRequest) -> EvaluationSchemeRequest:
    return EvaluationSchemeRequest(categories=list(categories))


def test_create_valid_100_percent_scheme_succeeds(db_session: Session) -> None:
    course_id = _course(db_session)

    result = replace_evaluation_scheme(
        db_session,
        course_id,
        _scheme(
            CategorySchemeRequest(name="Tasks", weight_percent=Decimal("60"), sort_order=1),
            CategorySchemeRequest(name="Exams", weight_percent=Decimal("40"), sort_order=2),
        ),
    )

    assert {c.name for c in result.categories} == {"Tasks", "Exams"}


def test_total_weight_below_100_is_rejected(db_session: Session) -> None:
    course_id = _course(db_session)

    with pytest.raises(InvalidEvaluationSchemeError):
        replace_evaluation_scheme(
            db_session,
            course_id,
            _scheme(
                CategorySchemeRequest(name="Tasks", weight_percent=Decimal("90"), sort_order=1)
            ),
        )


def test_total_weight_above_100_is_rejected(db_session: Session) -> None:
    course_id = _course(db_session)

    with pytest.raises(InvalidEvaluationSchemeError):
        replace_evaluation_scheme(
            db_session,
            course_id,
            _scheme(
                CategorySchemeRequest(name="Tasks", weight_percent=Decimal("60"), sort_order=1),
                CategorySchemeRequest(name="Exams", weight_percent=Decimal("50"), sort_order=2),
            ),
        )


def test_decimal_category_weights_are_accepted(db_session: Session) -> None:
    course_id = _course(db_session)

    result = replace_evaluation_scheme(
        db_session,
        course_id,
        _scheme(
            CategorySchemeRequest(name="A", weight_percent=Decimal("12.50"), sort_order=1),
            CategorySchemeRequest(name="B", weight_percent=Decimal("87.50"), sort_order=2),
        ),
    )

    weights = {c.name: c.weight_percent for c in result.categories}
    assert weights["A"] == 12.5
    assert weights["B"] == 87.5


def test_duplicate_grade_item_assignment_is_rejected(db_session: Session) -> None:
    course_id = _course(db_session)
    item_id = _grade_item(db_session, course_id)

    with pytest.raises(InvalidEvaluationSchemeError):
        replace_evaluation_scheme(
            db_session,
            course_id,
            _scheme(
                CategorySchemeRequest(
                    name="A",
                    weight_percent=Decimal("50"),
                    sort_order=1,
                    grade_items=[
                        GradeItemAssignmentRequest(
                            grade_item_id=item_id, counts_toward_current_grade=True
                        )
                    ],
                ),
                CategorySchemeRequest(
                    name="B",
                    weight_percent=Decimal("50"),
                    sort_order=2,
                    grade_items=[
                        GradeItemAssignmentRequest(
                            grade_item_id=item_id, counts_toward_current_grade=True
                        )
                    ],
                ),
            ),
        )


def test_grade_item_from_another_course_is_rejected(db_session: Session) -> None:
    course_id = _course(db_session, "Course A")
    other_course_id = _course(db_session, "Course B")
    other_item_id = _grade_item(db_session, other_course_id)

    with pytest.raises(InvalidEvaluationSchemeError):
        replace_evaluation_scheme(
            db_session,
            course_id,
            _scheme(
                CategorySchemeRequest(
                    name="A",
                    weight_percent=Decimal("100"),
                    sort_order=1,
                    grade_items=[
                        GradeItemAssignmentRequest(
                            grade_item_id=other_item_id, counts_toward_current_grade=True
                        )
                    ],
                )
            ),
        )


def test_unknown_grade_item_is_rejected(db_session: Session) -> None:
    course_id = _course(db_session)

    with pytest.raises(InvalidEvaluationSchemeError):
        replace_evaluation_scheme(
            db_session,
            course_id,
            _scheme(
                CategorySchemeRequest(
                    name="A",
                    weight_percent=Decimal("100"),
                    sort_order=1,
                    grade_items=[
                        GradeItemAssignmentRequest(
                            grade_item_id=999_999, counts_toward_current_grade=True
                        )
                    ],
                )
            ),
        )


def test_configuration_update_is_atomic_on_failure(db_session: Session) -> None:
    """An invalid second PUT must leave the first, valid scheme
    completely untouched — no partial category/assignment writes.
    """
    course_id = _course(db_session)
    item_id = _grade_item(db_session, course_id)
    replace_evaluation_scheme(
        db_session,
        course_id,
        _scheme(
            CategorySchemeRequest(
                name="Tasks",
                weight_percent=Decimal("100"),
                sort_order=1,
                grade_items=[
                    GradeItemAssignmentRequest(
                        grade_item_id=item_id, counts_toward_current_grade=True
                    )
                ],
            )
        ),
    )

    with pytest.raises(InvalidEvaluationSchemeError):
        replace_evaluation_scheme(
            db_session,
            course_id,
            _scheme(
                CategorySchemeRequest(name="Broken", weight_percent=Decimal("50"), sort_order=1)
            ),
        )

    unchanged = get_evaluation_scheme(db_session, course_id)
    assert len(unchanged.categories) == 1
    assert unchanged.categories[0].name == "Tasks"
    assert unchanged.categories[0].grade_items[0].grade_item_id == item_id


def test_atomic_replace_removes_previous_categories_and_assignments(db_session: Session) -> None:
    course_id = _course(db_session)
    item_id = _grade_item(db_session, course_id)
    replace_evaluation_scheme(
        db_session,
        course_id,
        _scheme(
            CategorySchemeRequest(
                name="Old",
                weight_percent=Decimal("100"),
                sort_order=1,
                grade_items=[
                    GradeItemAssignmentRequest(
                        grade_item_id=item_id, counts_toward_current_grade=True
                    )
                ],
            )
        ),
    )
    old_category_id = (
        db_session.execute(select(GradeCategory.id).where(GradeCategory.name == "Old")).scalar_one()
    )

    replace_evaluation_scheme(
        db_session,
        course_id,
        _scheme(CategorySchemeRequest(name="New", weight_percent=Decimal("100"), sort_order=1)),
    )

    assert (
        db_session.execute(
            select(GradeCategory).where(GradeCategory.id == old_category_id)
        ).scalar_one_or_none()
        is None
    )
    assert (
        db_session.execute(
            select(GradeItemEvaluation).where(GradeItemEvaluation.grade_item_id == item_id)
        ).scalar_one_or_none()
        is None
    )
