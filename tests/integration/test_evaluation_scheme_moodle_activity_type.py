"""moodle_activity_type on evaluation categories — validation, persistence and
the database constraint. See app.services.evaluation_service
._validate_evaluation_scheme and academic.grade_categories
(uq_grade_categories_course_moodle_activity_type).
"""

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.academic.models import Course, GradeCategory
from app.api.schemas.evaluation_scheme import CategorySchemeRequest, EvaluationSchemeRequest
from app.services.evaluation_service import (
    InvalidEvaluationSchemeError,
    get_evaluation_scheme,
    replace_evaluation_scheme,
)


def _course(db_session: Session, name: str = "Course") -> int:
    course = Course(name=name)
    db_session.add(course)
    db_session.commit()
    return course.id


def _cat(
    name: str,
    weight: str,
    sort_order: int,
    moodle_activity_type: str | None = None,
    calculation_type: str = "GRADE_ITEMS",
) -> CategorySchemeRequest:
    return CategorySchemeRequest(
        name=name,
        weight_percent=Decimal(weight),
        sort_order=sort_order,
        moodle_activity_type=moodle_activity_type,
        calculation_type=calculation_type,  # type: ignore[arg-type]
    )


def _put(db_session: Session, course_id: int, *categories: CategorySchemeRequest):  # noqa: ANN202
    return replace_evaluation_scheme(
        db_session, course_id, EvaluationSchemeRequest(categories=list(categories))
    )


def test_two_categories_with_the_same_moodle_activity_type_are_rejected(
    db_session: Session,
) -> None:
    course_id = _course(db_session)

    with pytest.raises(InvalidEvaluationSchemeError, match="more than one category"):
        _put(
            db_session,
            course_id,
            _cat("A", "50", 1, "assign"),
            _cat("B", "50", 2, "assign"),
        )


def test_a_rejected_payload_changes_nothing(db_session: Session) -> None:
    course_id = _course(db_session)
    _put(db_session, course_id, _cat("Tareas", "100", 1, "assign"))

    with pytest.raises(InvalidEvaluationSchemeError):
        _put(db_session, course_id, _cat("A", "50", 1, "quiz"), _cat("B", "50", 2, "quiz"))

    scheme = get_evaluation_scheme(db_session, course_id)
    assert [(c.name, c.moodle_activity_type) for c in scheme.categories] == [("Tareas", "assign")]


def test_attendance_participation_category_without_a_moodle_type_is_valid(
    db_session: Session,
) -> None:
    course_id = _course(db_session)

    scheme = _put(
        db_session,
        course_id,
        _cat("Entregables / tareas", "40", 1, "assign"),
        _cat("Participación / asistencia", "20", 2, None, "ATTENDANCE_PARTICIPATION"),
        _cat("Exámenes", "40", 3, "quiz"),
    )

    by_name = {c.name: c for c in scheme.categories}
    assert by_name["Participación / asistencia"].moodle_activity_type is None
    assert by_name["Participación / asistencia"].calculation_type == "ATTENDANCE_PARTICIPATION"
    assert by_name["Entregables / tareas"].moodle_activity_type == "assign"
    assert by_name["Exámenes"].moodle_activity_type == "quiz"


def test_attendance_participation_category_cannot_have_a_moodle_type(
    db_session: Session,
) -> None:
    course_id = _course(db_session)

    with pytest.raises(InvalidEvaluationSchemeError, match="does not come from Moodle"):
        _put(
            db_session,
            course_id,
            _cat("Participación", "100", 1, "assign", "ATTENDANCE_PARTICIPATION"),
        )


def test_the_field_is_optional_and_defaults_to_null(db_session: Session) -> None:
    course_id = _course(db_session)

    request_category = CategorySchemeRequest(
        name="Tareas", weight_percent=Decimal("100"), sort_order=1
    )
    scheme = replace_evaluation_scheme(
        db_session, course_id, EvaluationSchemeRequest(categories=[request_category])
    )

    assert request_category.moodle_activity_type is None
    assert scheme.categories[0].moodle_activity_type is None


def test_several_categories_without_a_moodle_type_are_allowed(db_session: Session) -> None:
    course_id = _course(db_session)

    scheme = _put(db_session, course_id, _cat("A", "30", 1), _cat("B", "30", 2), _cat("C", "40", 3))

    assert [c.moodle_activity_type for c in scheme.categories] == [None, None, None]


def test_moodle_activity_types_are_an_open_list(db_session: Session) -> None:
    """No closed list of Moodle types: any itemmodule string can be mapped."""
    course_id = _course(db_session)

    scheme = _put(
        db_session,
        course_id,
        _cat("Foros", "40", 1, "forum"),
        _cat("Talleres", "30", 2, "workshop"),
        _cat("Lecciones", "30", 3, "lesson"),
    )

    assert {c.moodle_activity_type for c in scheme.categories} == {"forum", "workshop", "lesson"}


def test_the_same_type_may_be_used_by_different_courses(db_session: Session) -> None:
    first, second = _course(db_session, "First"), _course(db_session, "Second")

    _put(db_session, first, _cat("Tareas", "100", 1, "assign"))
    scheme = _put(db_session, second, _cat("Tareas", "100", 1, "assign"))

    assert scheme.categories[0].moodle_activity_type == "assign"


# -- the database constraint itself ----------------------------------------


def test_the_database_rejects_two_categories_of_a_course_with_the_same_type(
    db_session: Session,
) -> None:
    course_id = _course(db_session)
    db_session.add(
        GradeCategory(
            course_id=course_id,
            name="A",
            weight_percent=50,
            sort_order=1,
            moodle_activity_type="assign",
        )
    )
    db_session.commit()

    db_session.add(
        GradeCategory(
            course_id=course_id,
            name="B",
            weight_percent=50,
            sort_order=2,
            moodle_activity_type="assign",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_the_database_allows_many_null_types_in_one_course(db_session: Session) -> None:
    course_id = _course(db_session)

    db_session.add_all(
        [
            GradeCategory(course_id=course_id, name=name, weight_percent=30, sort_order=i)
            for i, name in enumerate(("A", "B", "C"), start=1)
        ]
    )
    db_session.commit()

    count = db_session.query(GradeCategory).filter_by(course_id=course_id).count()
    assert count == 3
