"""The weighted evaluation engine's arithmetic — see
app.services.evaluation_service.get_student_evaluation. Uses the
SAVEPOINT-rollback db_session fixture (replace_evaluation_scheme commits
internally, which the fixture tolerates by design).
"""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.academic.models import Course, GradeItem, Student, StudentGrade
from app.api.schemas.evaluation_scheme import (
    CategorySchemeRequest,
    EvaluationSchemeRequest,
    GradeItemAssignmentRequest,
)
from app.services.evaluation_service import get_student_evaluation, replace_evaluation_scheme


def _course(db_session: Session) -> int:
    course = Course(name="Test Course")
    db_session.add(course)
    db_session.commit()
    return course.id


def _student(db_session: Session, account_number: str) -> int:
    student = Student(account_number=account_number, first_name="Test", last_name="Student")
    db_session.add(student)
    db_session.commit()
    return student.id


def _grade_item(db_session: Session, course_id: int, name: str, max_grade: str = "100") -> int:
    item = GradeItem(course_id=course_id, name=name, max_grade=Decimal(max_grade))
    db_session.add(item)
    db_session.commit()
    return item.id


def _grade(db_session: Session, grade_item_id: int, student_id: int, grade: str | None) -> None:
    db_session.add(
        StudentGrade(
            grade_item_id=grade_item_id,
            student_id=student_id,
            grade=Decimal(grade) if grade is not None else None,
        )
    )
    db_session.commit()


def _assign(item_id: int, counts: bool = True) -> GradeItemAssignmentRequest:
    return GradeItemAssignmentRequest(grade_item_id=item_id, counts_toward_current_grade=counts)


def test_single_activity_category(db_session: Session) -> None:
    course_id = _course(db_session)
    student_id = _student(db_session, "77001")
    item_id = _grade_item(db_session, course_id, "Tarea 01")
    _grade(db_session, item_id, student_id, "80")
    replace_evaluation_scheme(
        db_session,
        course_id,
        EvaluationSchemeRequest(
            categories=[
                CategorySchemeRequest(
                    name="Tasks",
                    weight_percent=Decimal("100"),
                    sort_order=1,
                    grade_items=[_assign(item_id)],
                )
            ]
        ),
    )

    result = get_student_evaluation(db_session, student_id, course_id)

    category = result.categories[0]
    assert category.category_score_100 == 80.0
    assert category.counted_items == 1
    assert category.graded_items == 1


def test_multiple_activity_category_equal_weighting(db_session: Session) -> None:
    course_id = _course(db_session)
    student_id = _student(db_session, "77002")
    item_1 = _grade_item(db_session, course_id, "Tarea 01")
    item_2 = _grade_item(db_session, course_id, "Tarea 02")
    item_3 = _grade_item(db_session, course_id, "Tarea 03")
    _grade(db_session, item_1, student_id, "80")
    _grade(db_session, item_2, student_id, "100")
    _grade(db_session, item_3, student_id, "70")
    replace_evaluation_scheme(
        db_session,
        course_id,
        EvaluationSchemeRequest(
            categories=[
                CategorySchemeRequest(
                    name="Tasks",
                    weight_percent=Decimal("100"),
                    sort_order=1,
                    grade_items=[_assign(item_1), _assign(item_2), _assign(item_3)],
                )
            ]
        ),
    )

    result = get_student_evaluation(db_session, student_id, course_id)

    # (80 + 100 + 70) / 3 = 83.333... -> rounds to 83.33
    assert result.categories[0].category_score_100 == 83.33


def test_null_grade_excluded_from_numeric_average(db_session: Session) -> None:
    course_id = _course(db_session)
    student_id = _student(db_session, "77003")
    item_1 = _grade_item(db_session, course_id, "Tarea 01")
    item_2 = _grade_item(db_session, course_id, "Tarea 02")
    _grade(db_session, item_1, student_id, "80")
    _grade(db_session, item_2, student_id, None)
    replace_evaluation_scheme(
        db_session,
        course_id,
        EvaluationSchemeRequest(
            categories=[
                CategorySchemeRequest(
                    name="Tasks",
                    weight_percent=Decimal("100"),
                    sort_order=1,
                    grade_items=[_assign(item_1), _assign(item_2)],
                )
            ]
        ),
    )

    result = get_student_evaluation(db_session, student_id, course_id)

    category = result.categories[0]
    # Average of ONLY the graded item (80), never (80+0)/2=40.
    assert category.category_score_100 == 80.0
    assert category.counted_items == 2
    assert category.graded_items == 1
    assert category.ungraded_items == 1


def test_actual_zero_is_included_in_the_average(db_session: Session) -> None:
    course_id = _course(db_session)
    student_id = _student(db_session, "77004")
    item_1 = _grade_item(db_session, course_id, "Tarea 01")
    item_2 = _grade_item(db_session, course_id, "Tarea 02")
    _grade(db_session, item_1, student_id, "80")
    _grade(db_session, item_2, student_id, "0")
    replace_evaluation_scheme(
        db_session,
        course_id,
        EvaluationSchemeRequest(
            categories=[
                CategorySchemeRequest(
                    name="Tasks",
                    weight_percent=Decimal("100"),
                    sort_order=1,
                    grade_items=[_assign(item_1), _assign(item_2)],
                )
            ]
        ),
    )

    result = get_student_evaluation(db_session, student_id, course_id)

    category = result.categories[0]
    # (80 + 0) / 2 = 40 -- the real zero pulls the average down.
    assert category.category_score_100 == 40.0
    assert category.graded_items == 2
    assert category.ungraded_items == 0


def test_non_counted_item_excluded_from_calculation(db_session: Session) -> None:
    course_id = _course(db_session)
    student_id = _student(db_session, "77005")
    counted_item = _grade_item(db_session, course_id, "Tarea 01")
    future_item = _grade_item(db_session, course_id, "Tarea 02")
    _grade(db_session, counted_item, student_id, "80")
    _grade(db_session, future_item, student_id, "0")
    replace_evaluation_scheme(
        db_session,
        course_id,
        EvaluationSchemeRequest(
            categories=[
                CategorySchemeRequest(
                    name="Tasks",
                    weight_percent=Decimal("100"),
                    sort_order=1,
                    grade_items=[_assign(counted_item), _assign(future_item, counts=False)],
                )
            ]
        ),
    )

    result = get_student_evaluation(db_session, student_id, course_id)

    category = result.categories[0]
    assert category.category_score_100 == 80.0
    assert category.counted_items == 1


def test_category_contribution_is_weight_times_score(db_session: Session) -> None:
    course_id = _course(db_session)
    student_id = _student(db_session, "77006")
    item_id = _grade_item(db_session, course_id, "Tarea 01")
    _grade(db_session, item_id, student_id, "80")
    replace_evaluation_scheme(
        db_session,
        course_id,
        EvaluationSchemeRequest(
            categories=[
                CategorySchemeRequest(
                    name="Tasks",
                    weight_percent=Decimal("30"),
                    sort_order=1,
                    grade_items=[_assign(item_id)],
                ),
                CategorySchemeRequest(name="Rest", weight_percent=Decimal("70"), sort_order=2),
            ]
        ),
    )

    result = get_student_evaluation(db_session, student_id, course_id)

    tasks = next(c for c in result.categories if c.name == "Tasks")
    assert tasks.contribution_points == 24.0  # 80 * 30 / 100


def test_counted_graded_ungraded_item_counts_are_correct(db_session: Session) -> None:
    course_id = _course(db_session)
    student_id = _student(db_session, "77007")
    graded = _grade_item(db_session, course_id, "Graded")
    ungraded = _grade_item(db_session, course_id, "Ungraded")
    not_counted = _grade_item(db_session, course_id, "NotCounted")
    _grade(db_session, graded, student_id, "50")
    _grade(db_session, ungraded, student_id, None)
    _grade(db_session, not_counted, student_id, "90")
    replace_evaluation_scheme(
        db_session,
        course_id,
        EvaluationSchemeRequest(
            categories=[
                CategorySchemeRequest(
                    name="Cat",
                    weight_percent=Decimal("100"),
                    sort_order=1,
                    grade_items=[
                        _assign(graded),
                        _assign(ungraded),
                        _assign(not_counted, counts=False),
                    ],
                )
            ]
        ),
    )

    result = get_student_evaluation(db_session, student_id, course_id)

    category = result.categories[0]
    assert category.counted_items == 2
    assert category.graded_items == 1
    assert category.ungraded_items == 1


def test_overall_grade_worked_example(db_session: Session) -> None:
    """The exact example from the spec:
    Tasks: weight=30, score=80 -> contribution 24
    Exams: weight=20, score=60 -> contribution 12
    weighted_points_earned=36, evaluated_weight=50,
    current_score_100=72, current_grade_10=7.2
    """
    course_id = _course(db_session)
    student_id = _student(db_session, "77008")
    tasks_item = _grade_item(db_session, course_id, "Tarea 01")
    exams_item = _grade_item(db_session, course_id, "Examen 1")
    project_item = _grade_item(db_session, course_id, "Proyecto")
    _grade(db_session, tasks_item, student_id, "80")
    _grade(db_session, exams_item, student_id, "60")
    _grade(db_session, project_item, student_id, None)
    replace_evaluation_scheme(
        db_session,
        course_id,
        EvaluationSchemeRequest(
            categories=[
                CategorySchemeRequest(
                    name="Tasks",
                    weight_percent=Decimal("30"),
                    sort_order=1,
                    grade_items=[_assign(tasks_item)],
                ),
                CategorySchemeRequest(
                    name="Exams",
                    weight_percent=Decimal("20"),
                    sort_order=2,
                    grade_items=[_assign(exams_item)],
                ),
                CategorySchemeRequest(
                    name="Project",
                    weight_percent=Decimal("30"),
                    sort_order=3,
                    grade_items=[_assign(project_item)],
                ),
                CategorySchemeRequest(
                    name="Participation", weight_percent=Decimal("20"), sort_order=4
                ),
            ]
        ),
    )

    result = get_student_evaluation(db_session, student_id, course_id)

    tasks = next(c for c in result.categories if c.name == "Tasks")
    exams = next(c for c in result.categories if c.name == "Exams")
    assert tasks.contribution_points == 24.0
    assert exams.contribution_points == 12.0
    assert result.weighted_points_earned == 36.0
    assert result.evaluated_weight_percent == 50.0
    assert result.current_score_100 == 72.0
    assert result.current_grade_10 == 7.2


def test_zero_evaluated_weight_returns_null_not_zero(db_session: Session) -> None:
    course_id = _course(db_session)
    student_id = _student(db_session, "77009")
    item_id = _grade_item(db_session, course_id, "Tarea 01")
    _grade(db_session, item_id, student_id, None)  # ungraded -> category not calculable
    replace_evaluation_scheme(
        db_session,
        course_id,
        EvaluationSchemeRequest(
            categories=[
                CategorySchemeRequest(
                    name="Tasks",
                    weight_percent=Decimal("100"),
                    sort_order=1,
                    grade_items=[_assign(item_id)],
                )
            ]
        ),
    )

    result = get_student_evaluation(db_session, student_id, course_id)

    assert result.evaluated_weight_percent == 0.0
    assert result.current_score_100 is None
    assert result.current_grade_10 is None


def test_evaluation_response_is_fully_transparent_and_reconstructable(db_session: Session) -> None:
    """Every final number must be derivable purely from the items/
    categories in the response — no opaque final number.
    """
    course_id = _course(db_session)
    student_id = _student(db_session, "77010")
    tasks_item = _grade_item(db_session, course_id, "Tarea 01")
    exams_item = _grade_item(db_session, course_id, "Examen 1")
    project_item = _grade_item(db_session, course_id, "Proyecto")
    _grade(db_session, tasks_item, student_id, "80")
    _grade(db_session, exams_item, student_id, "60")
    _grade(db_session, project_item, student_id, None)
    replace_evaluation_scheme(
        db_session,
        course_id,
        EvaluationSchemeRequest(
            categories=[
                CategorySchemeRequest(
                    name="Tasks",
                    weight_percent=Decimal("30"),
                    sort_order=1,
                    grade_items=[_assign(tasks_item)],
                ),
                CategorySchemeRequest(
                    name="Exams",
                    weight_percent=Decimal("20"),
                    sort_order=2,
                    grade_items=[_assign(exams_item)],
                ),
                CategorySchemeRequest(
                    name="Project",
                    weight_percent=Decimal("30"),
                    sort_order=3,
                    grade_items=[_assign(project_item)],
                ),
                CategorySchemeRequest(
                    name="Participation", weight_percent=Decimal("20"), sort_order=4
                ),
            ]
        ),
    )

    result = get_student_evaluation(db_session, student_id, course_id)

    # Reconstruct category_score_100 from each category's own items.
    for category in result.categories:
        graded_scores = [i.score_100 for i in category.items if i.score_100 is not None]
        if graded_scores:
            expected_avg = round(sum(graded_scores) / len(graded_scores), 2)
            assert category.category_score_100 == expected_avg

    # Reconstruct weighted_points_earned/evaluated_weight from categories.
    reconstructed_points = sum(
        c.contribution_points for c in result.categories if c.contribution_points is not None
    )
    reconstructed_weight = sum(
        c.weight_percent for c in result.categories if c.contribution_points is not None
    )
    assert round(reconstructed_points, 2) == result.weighted_points_earned
    assert round(reconstructed_weight, 2) == result.evaluated_weight_percent

    # Reconstruct current_score_100/current_grade_10 from those two.
    expected_score = round(
        result.weighted_points_earned / result.evaluated_weight_percent * 100, 2
    )
    assert result.current_score_100 == expected_score
    assert round(result.current_score_100 / 10, 2) == result.current_grade_10
