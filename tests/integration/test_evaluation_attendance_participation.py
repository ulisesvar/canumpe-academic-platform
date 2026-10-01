"""The ATTENDANCE_PARTICIPATION evaluation strategy (Phase 8.3) — see
app.services.evaluation_service.get_student_evaluation. Uses the
SAVEPOINT-rollback db_session fixture.

Scheme used throughout unless stated: Tasks 40% (GRADE_ITEMS, one item
graded 80), Attendance/Participation 20% (ATTENDANCE_PARTICIPATION),
Exams 40% (GRADE_ITEMS, nothing graded).
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.academic.models import (
    AttendanceRecord,
    AttendanceSession,
    Course,
    Enrollment,
    GradeItem,
    ParticipationObservation,
    Student,
    StudentGrade,
)
from app.api.schemas.evaluation import CategoryEvaluation, StudentEvaluationResponse
from app.api.schemas.evaluation_scheme import (
    CategorySchemeRequest,
    EvaluationSchemeRequest,
    GradeItemAssignmentRequest,
)
from app.services.evaluation_service import (
    InvalidEvaluationSchemeError,
    get_student_evaluation,
    replace_evaluation_scheme,
)

T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
_AP = "ATTENDANCE_PARTICIPATION"


def _course(db_session: Session, name: str = "Course") -> int:
    course = Course(name=name)
    db_session.add(course)
    db_session.commit()
    return course.id


def _student(db_session: Session, account_number: str, course_id: int) -> int:
    student = Student(account_number=account_number, first_name="A", last_name="B")
    db_session.add(student)
    db_session.commit()
    db_session.add(Enrollment(student_id=student.id, course_id=course_id))
    db_session.commit()
    return student.id


def _item(
    db_session: Session, course_id: int, name: str, grade: str | None, student_id: int
) -> int:
    item = GradeItem(course_id=course_id, name=name, max_grade=Decimal(100))
    db_session.add(item)
    db_session.commit()
    if grade is not None:
        db_session.add(
            StudentGrade(grade_item_id=item.id, student_id=student_id, grade=Decimal(grade))
        )
        db_session.commit()
    return item.id


def _sessions(
    db_session: Session,
    course_id: int,
    student_id: int,
    *,
    closed: int,
    attended: int,
    open_: int = 0,
) -> None:
    for n in range(closed + open_):
        is_closed = n < closed
        session = AttendanceSession(
            course_id=course_id,
            opened_at=T0 + timedelta(days=n),
            closed_at=T0 + timedelta(days=n, hours=1) if is_closed else None,
            status="CLOSED" if is_closed else "OPEN",
        )
        db_session.add(session)
        db_session.commit()
        if n < attended:
            db_session.add(
                AttendanceRecord(
                    attendance_session_id=session.id, student_id=student_id, recorded_at=T0
                )
            )
            db_session.commit()


def _observe(db_session: Session, course_id: int, student_id: int, *values: int) -> None:
    for value in values:
        db_session.add(
            ParticipationObservation(course_id=course_id, student_id=student_id, value=value)
        )
    db_session.commit()


def _scheme(
    db_session: Session,
    course_id: int,
    task_item: int,
    exam_item: int,
    *,
    ap_weight: str = "20",
    ap_name: str = "Attendance / Participation",
) -> None:
    replace_evaluation_scheme(
        db_session,
        course_id,
        EvaluationSchemeRequest(
            categories=[
                CategorySchemeRequest(
                    name="Tasks",
                    weight_percent=Decimal("40"),
                    sort_order=1,
                    grade_items=[
                        GradeItemAssignmentRequest(
                            grade_item_id=task_item, counts_toward_current_grade=True
                        )
                    ],
                ),
                CategorySchemeRequest(
                    name=ap_name,
                    weight_percent=Decimal(ap_weight),
                    sort_order=2,
                    calculation_type=_AP,
                ),
                CategorySchemeRequest(
                    name="Exams",
                    weight_percent=Decimal(100) - Decimal(40) - Decimal(ap_weight),
                    sort_order=3,
                    grade_items=[
                        GradeItemAssignmentRequest(
                            grade_item_id=exam_item, counts_toward_current_grade=True
                        )
                    ],
                ),
            ]
        ),
    )


def _setup(db_session: Session, account: str, *, ap_weight: str = "20") -> tuple[int, int]:
    course_id = _course(db_session)
    student_id = _student(db_session, account, course_id)
    task = _item(db_session, course_id, "Tarea 01", "80", student_id)
    exam = _item(db_session, course_id, "Examen 01", None, student_id)
    _scheme(db_session, course_id, task, exam, ap_weight=ap_weight)
    return course_id, student_id


def _category(response: StudentEvaluationResponse, name: str) -> CategoryEvaluation:
    return next(c for c in response.categories if c.name == name)


def test_attendance_90_and_participation_average_2(db_session: Session) -> None:
    course_id, student_id = _setup(db_session, "8401")
    _sessions(db_session, course_id, student_id, closed=10, attended=9)
    _observe(db_session, course_id, student_id, 2)

    category = _category(
        get_student_evaluation(db_session, student_id, course_id), "Attendance / Participation"
    )

    # attendance 90; participation 2/3*100 = 66.666...; 90*0.33 + 66.666...*0.67 = 74.3666...
    assert category.category_score_100 == 74.37
    assert category.contribution_points == 14.87  # 74.3666... * 20 / 100
    assert category.weight_percent == 20.0
    assert category.items == []
    assert (category.counted_items, category.graded_items, category.ungraded_items) == (0, 0, 0)


def test_attendance_90_and_participation_zero_is_a_real_zero(db_session: Session) -> None:
    course_id, student_id = _setup(db_session, "8402")
    _sessions(db_session, course_id, student_id, closed=10, attended=9)
    _observe(db_session, course_id, student_id, 0)

    category = _category(
        get_student_evaluation(db_session, student_id, course_id), "Attendance / Participation"
    )

    assert category.category_score_100 == 29.7  # 90 * 0.33 + 0 * 0.67
    assert category.contribution_points == 5.94


def test_attendance_zero_and_participation_three_is_a_real_zero(db_session: Session) -> None:
    course_id, student_id = _setup(db_session, "8403")
    _sessions(db_session, course_id, student_id, closed=10, attended=0)
    _observe(db_session, course_id, student_id, 3)

    category = _category(
        get_student_evaluation(db_session, student_id, course_id), "Attendance / Participation"
    )

    assert category.category_score_100 == 67.0  # 0 * 0.33 + 100 * 0.67
    assert category.contribution_points == 13.4


def test_full_attendance_and_zero_participation_isolates_the_33_percent_share(
    db_session: Session,
) -> None:
    course_id, student_id = _setup(db_session, "8404")
    _sessions(db_session, course_id, student_id, closed=4, attended=4)
    _observe(db_session, course_id, student_id, 0, 0)

    category = _category(
        get_student_evaluation(db_session, student_id, course_id), "Attendance / Participation"
    )

    assert category.category_score_100 == 33.0


def test_number_of_participation_observations_does_not_change_the_category(
    db_session: Session,
) -> None:
    course_id, five_id = _setup(db_session, "8405")
    two_id = _student(db_session, "8406", course_id)
    _observe(db_session, course_id, five_id, *([3] * 5))
    _observe(db_session, course_id, two_id, *([3] * 2))
    # Same attendance for both: no closed sessions would make both NULL, so add some.
    for n in range(4):
        session = AttendanceSession(
            course_id=course_id, opened_at=T0 + timedelta(days=n), closed_at=T0, status="CLOSED"
        )
        db_session.add(session)
        db_session.commit()
        for student_id in (five_id, two_id):
            db_session.add(
                AttendanceRecord(
                    attendance_session_id=session.id, student_id=student_id, recorded_at=T0
                )
            )
        db_session.commit()

    five = _category(
        get_student_evaluation(db_session, five_id, course_id), "Attendance / Participation"
    )
    two = _category(
        get_student_evaluation(db_session, two_id, course_id), "Attendance / Participation"
    )

    assert five.category_score_100 == two.category_score_100 == 100.0


def test_no_participation_observations_count_as_zero_participation(db_session: Session) -> None:
    course_id, student_id = _setup(db_session, "8407")
    _sessions(db_session, course_id, student_id, closed=10, attended=9)  # attendance 90

    category = _category(
        get_student_evaluation(db_session, student_id, course_id), "Attendance / Participation"
    )

    assert category.category_score_100 == 29.7  # 90 * 0.33 + 0 * 0.67
    assert category.contribution_points == 5.94  # 29.7 * 20 / 100


def test_full_attendance_and_no_participation_observations_gives_33(db_session: Session) -> None:
    course_id, student_id = _setup(db_session, "8414")
    _sessions(db_session, course_id, student_id, closed=4, attended=4)  # attendance 100

    category = _category(
        get_student_evaluation(db_session, student_id, course_id), "Attendance / Participation"
    )

    assert category.category_score_100 == 33.0  # 100 * 0.33 + 0 * 0.67
    assert category.contribution_points == 6.6  # 33 * 20 / 100


def test_half_attendance_and_no_participation_observations_gives_16_5(
    db_session: Session,
) -> None:
    course_id, student_id = _setup(db_session, "8415")
    _sessions(db_session, course_id, student_id, closed=4, attended=2)  # attendance 50

    category = _category(
        get_student_evaluation(db_session, student_id, course_id), "Attendance / Participation"
    )

    assert category.category_score_100 == 16.5  # 50 * 0.33 + 0 * 0.67
    assert category.contribution_points == 3.3  # 16.5 * 20 / 100


def test_no_closed_attendance_sessions_makes_the_category_null(db_session: Session) -> None:
    course_id, student_id = _setup(db_session, "8408")
    _sessions(db_session, course_id, student_id, closed=0, attended=0, open_=3)
    _observe(db_session, course_id, student_id, 3, 3)

    category = _category(
        get_student_evaluation(db_session, student_id, course_id), "Attendance / Participation"
    )

    assert category.category_score_100 is None
    assert category.contribution_points is None


def test_a_null_category_is_excluded_from_evaluated_weight(db_session: Session) -> None:
    course_id, student_id = _setup(db_session, "8409")
    # No CLOSED session at all: attendance is genuinely not available, so the category is NULL
    # even though participation exists.
    _sessions(db_session, course_id, student_id, closed=0, attended=0, open_=3)
    _observe(db_session, course_id, student_id, 3, 3)

    result = get_student_evaluation(db_session, student_id, course_id)

    # Only Tasks (40%, graded 80) is calculable: Exams has nothing graded, A/P is NULL.
    assert result.evaluated_weight_percent == 40.0
    assert result.weighted_points_earned == 32.0
    assert result.current_score_100 == 80.0
    assert result.current_grade_10 == 8.0


def test_a_student_with_attendance_and_no_participation_is_evaluated_in_the_aggregates(
    db_session: Session,
) -> None:
    course_id, student_id = _setup(db_session, "8416")
    _sessions(db_session, course_id, student_id, closed=10, attended=9)  # no observations

    result = get_student_evaluation(db_session, student_id, course_id)

    assert result.evaluated_weight_percent == 60.0  # Tasks 40 + A/P 20 (now evaluable)
    assert result.weighted_points_earned == 37.94  # 32 + 5.94
    assert result.current_score_100 == 63.23  # 37.94 / 60 * 100
    assert result.current_grade_10 == 6.32


def test_current_grade_for_a_student_with_tasks_attendance_and_no_participation(
    db_session: Session,
) -> None:
    """Tareas 30, asistencia 100, sin participación (=0), examen 66.66667; pesos 40/20/40."""
    course_id = _course(db_session)
    student_id = _student(db_session, "8417", course_id)
    task = _item(db_session, course_id, "Tarea 01", "30", student_id)
    exam = _item(db_session, course_id, "Examen 1", "66.66667", student_id)
    _scheme(db_session, course_id, task, exam)
    _sessions(db_session, course_id, student_id, closed=7, attended=7)  # attendance 100

    result = get_student_evaluation(db_session, student_id, course_id)

    tasks = _category(result, "Tasks")
    participation = _category(result, "Attendance / Participation")
    exams = _category(result, "Exams")
    # GRADE_ITEMS categories are computed exactly as before.
    assert (tasks.category_score_100, tasks.contribution_points) == (30.0, 12.0)
    assert (exams.category_score_100, exams.contribution_points) == (66.67, 26.67)
    # 100 * 0.33 + 0 * 0.67 = 33; * 20% = 6.60
    assert (participation.category_score_100, participation.contribution_points) == (33.0, 6.6)
    assert result.evaluated_weight_percent == 100.0
    assert result.weighted_points_earned == 45.27  # 12 + 6.6 + 26.666668
    assert result.current_score_100 == 45.27
    assert result.current_grade_10 == 4.53


def test_once_both_components_exist_the_category_contributes_its_configured_weight(
    db_session: Session,
) -> None:
    course_id, student_id = _setup(db_session, "8410")
    _sessions(db_session, course_id, student_id, closed=4, attended=4)  # attendance 100
    _observe(db_session, course_id, student_id, 3)  # participation 100

    result = get_student_evaluation(db_session, student_id, course_id)
    category = _category(result, "Attendance / Participation")

    assert category.category_score_100 == 100.0
    assert category.contribution_points == 20.0  # 100 * 20 / 100
    assert result.evaluated_weight_percent == 60.0  # Tasks 40 + A/P 20
    assert result.weighted_points_earned == 52.0  # 32 + 20
    assert result.current_score_100 == 86.67  # 52 / 60 * 100
    assert result.current_grade_10 == 8.67


def test_the_category_weight_is_configuration_not_hard_coded(db_session: Session) -> None:
    course_id, student_id = _setup(db_session, "8411", ap_weight="30")
    _sessions(db_session, course_id, student_id, closed=4, attended=4)
    _observe(db_session, course_id, student_id, 3)

    category = _category(
        get_student_evaluation(db_session, student_id, course_id), "Attendance / Participation"
    )

    assert category.weight_percent == 30.0
    assert category.contribution_points == 30.0  # 100 * 30 / 100


def test_the_strategy_comes_from_calculation_type_never_the_category_name(
    db_session: Session,
) -> None:
    course_id = _course(db_session)
    student_id = _student(db_session, "8412", course_id)
    item = _item(db_session, course_id, "Item", "50", student_id)
    _sessions(db_session, course_id, student_id, closed=4, attended=4)
    _observe(db_session, course_id, student_id, 3)
    replace_evaluation_scheme(
        db_session,
        course_id,
        EvaluationSchemeRequest(
            categories=[
                # Named like the attendance category, but GRADE_ITEMS: scored from its item.
                CategorySchemeRequest(
                    name="Attendance / Participation",
                    weight_percent=Decimal("50"),
                    sort_order=1,
                    grade_items=[
                        GradeItemAssignmentRequest(
                            grade_item_id=item, counts_toward_current_grade=True
                        )
                    ],
                ),
                # Named innocuously, but ATTENDANCE_PARTICIPATION.
                CategorySchemeRequest(
                    name="Otra cosa",
                    weight_percent=Decimal("50"),
                    sort_order=2,
                    calculation_type=_AP,
                ),
            ]
        ),
    )

    result = get_student_evaluation(db_session, student_id, course_id)

    assert _category(result, "Attendance / Participation").category_score_100 == 50.0
    assert _category(result, "Otra cosa").category_score_100 == 100.0


def test_grade_items_categories_are_unchanged_by_an_attendance_participation_category(
    db_session: Session,
) -> None:
    course_id, student_id = _setup(db_session, "8413")
    other_course_id = _course(db_session, "Plain")
    other_student = _student(db_session, "8414", other_course_id)
    task = _item(db_session, other_course_id, "Tarea 01", "80", other_student)
    exam = _item(db_session, other_course_id, "Examen 01", None, other_student)
    replace_evaluation_scheme(
        db_session,
        other_course_id,
        EvaluationSchemeRequest(
            categories=[
                CategorySchemeRequest(
                    name="Tasks",
                    weight_percent=Decimal("40"),
                    sort_order=1,
                    grade_items=[
                        GradeItemAssignmentRequest(
                            grade_item_id=task, counts_toward_current_grade=True
                        )
                    ],
                ),
                CategorySchemeRequest(
                    name="Exams",
                    weight_percent=Decimal("60"),
                    sort_order=2,
                    grade_items=[
                        GradeItemAssignmentRequest(
                            grade_item_id=exam, counts_toward_current_grade=True
                        )
                    ],
                ),
            ]
        ),
    )

    with_ap = _category(get_student_evaluation(db_session, student_id, course_id), "Tasks")
    without_ap = _category(
        get_student_evaluation(db_session, other_student, other_course_id), "Tasks"
    )

    assert with_ap.category_score_100 == without_ap.category_score_100 == 80.0
    assert with_ap.contribution_points == without_ap.contribution_points == 32.0
    assert (with_ap.counted_items, with_ap.graded_items, with_ap.ungraded_items) == (1, 1, 0)


# -- scheme validation --------------------------------------------------


def test_attendance_participation_category_cannot_contain_grade_items(db_session: Session) -> None:
    course_id = _course(db_session)
    student_id = _student(db_session, "8415", course_id)
    item = _item(db_session, course_id, "Item", "50", student_id)

    with pytest.raises(InvalidEvaluationSchemeError, match="cannot contain grade items"):
        replace_evaluation_scheme(
            db_session,
            course_id,
            EvaluationSchemeRequest(
                categories=[
                    CategorySchemeRequest(
                        name="A/P",
                        weight_percent=Decimal("100"),
                        sort_order=1,
                        calculation_type=_AP,
                        grade_items=[
                            GradeItemAssignmentRequest(
                                grade_item_id=item, counts_toward_current_grade=True
                            )
                        ],
                    )
                ]
            ),
        )


def test_more_than_one_attendance_participation_category_is_rejected(db_session: Session) -> None:
    course_id = _course(db_session)

    with pytest.raises(InvalidEvaluationSchemeError, match="at most one"):
        replace_evaluation_scheme(
            db_session,
            course_id,
            EvaluationSchemeRequest(
                categories=[
                    CategorySchemeRequest(
                        name="A", weight_percent=Decimal("50"), sort_order=1, calculation_type=_AP
                    ),
                    CategorySchemeRequest(
                        name="B", weight_percent=Decimal("50"), sort_order=2, calculation_type=_AP
                    ),
                ]
            ),
        )


def test_omitting_the_attendance_participation_category_is_rejected_and_changes_nothing(
    db_session: Session,
) -> None:
    course_id, student_id = _setup(db_session, "8416")
    _sessions(db_session, course_id, student_id, closed=4, attended=4)
    _observe(db_session, course_id, student_id, 3)

    with pytest.raises(InvalidEvaluationSchemeError, match="must include one"):
        replace_evaluation_scheme(
            db_session,
            course_id,
            EvaluationSchemeRequest(
                categories=[
                    CategorySchemeRequest(name="Tasks", weight_percent=Decimal("100"), sort_order=1)
                ]
            ),
        )

    result = get_student_evaluation(db_session, student_id, course_id)
    assert _category(result, "Attendance / Participation").category_score_100 == 100.0
    assert [c.name for c in result.categories] == ["Tasks", "Attendance / Participation", "Exams"]
