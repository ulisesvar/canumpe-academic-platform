"""integration.sync_issues for a Moodle grade whose student_source_id
doesn't resolve to any academic student yet — mirrors the Attendance
pipeline's UNRESOLVED_STUDENT handling (see
tests/integration/attendance/test_sync_issues.py).
"""

from sqlalchemy import Engine, select

from app.academic.models import Student, StudentGrade
from app.integration.models import SyncIssue
from app.integration.moodle.grades_merge import UNRESOLVED_GRADE_STUDENT_ISSUE_TYPE
from app.integration.moodle.grades_sync import run_moodle_grades_sync
from tests.integration.moodle.fake_moodle import (
    insert_course,
    insert_grade_grade,
    insert_grade_item,
)
from tests.integration.moodle.grades_helpers import (
    seed_moodle_course_mapping,
    seed_moodle_student_mapping,
)

MOODLE_USER_ID = 3


def _seed_unresolved(moodle_engine: Engine, app_engine: Engine) -> tuple[int, int]:
    with moodle_engine.begin() as connection:
        course_id = insert_course(connection, fullname="Intro to Programming")
        item_id = insert_grade_item(connection, courseid=course_id, itemname="Tarea 01")
        grade_id = insert_grade_grade(
            connection, itemid=item_id, userid=MOODLE_USER_ID, finalgrade=30
        )
    seed_moodle_course_mapping(app_engine, course_id)
    return course_id, grade_id


def _get_issue(app_engine: Engine) -> SyncIssue:
    with app_engine.begin() as connection:
        issue = connection.execute(
            select(SyncIssue).where(SyncIssue.issue_type == UNRESOLVED_GRADE_STUDENT_ISSUE_TYPE)
        ).one_or_none()
    assert issue is not None, "expected an UNRESOLVED_GRADE_STUDENT sync_issues row"
    return issue


def test_unresolved_grade_student_does_not_create_an_academic_student(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    course_id, _ = _seed_unresolved(moodle_engine, app_engine)

    outcome = run_moodle_grades_sync(app_engine, moodle_engine, course_id)

    assert outcome.status == "SUCCESS"
    with app_engine.begin() as connection:
        assert connection.execute(select(Student)).all() == []
        assert connection.execute(select(StudentGrade)).all() == []


def test_unresolved_grade_student_creates_an_operational_sync_issue(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    course_id, grade_id = _seed_unresolved(moodle_engine, app_engine)

    outcome = run_moodle_grades_sync(app_engine, moodle_engine, course_id)

    assert outcome.status == "SUCCESS"
    assert outcome.merge_result is not None
    assert outcome.merge_result.counters.rows_skipped == 1
    issue = _get_issue(app_engine)
    assert issue.source_system == "moodle"
    assert issue.source_entity == "student_grade"
    assert issue.source_id == str(grade_id)
    assert issue.reference_value == str(MOODLE_USER_ID)
    assert issue.status == "OPEN"


def test_repeated_unresolved_case_does_not_duplicate_the_issue(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    course_id, _ = _seed_unresolved(moodle_engine, app_engine)

    run_moodle_grades_sync(app_engine, moodle_engine, course_id)
    run_moodle_grades_sync(app_engine, moodle_engine, course_id)

    with app_engine.begin() as connection:
        issues = connection.execute(
            select(SyncIssue).where(SyncIssue.issue_type == UNRESOLVED_GRADE_STUDENT_ISSUE_TYPE)
        ).all()
    assert len(issues) == 1


def test_later_student_resolution_imports_the_grade(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    course_id, _ = _seed_unresolved(moodle_engine, app_engine)
    first = run_moodle_grades_sync(app_engine, moodle_engine, course_id)
    assert first.status == "SUCCESS"
    assert first.merge_result is not None
    assert first.merge_result.counters.rows_skipped == 1

    academic_student_id = seed_moodle_student_mapping(app_engine, MOODLE_USER_ID)

    second = run_moodle_grades_sync(app_engine, moodle_engine, course_id)

    assert second.status == "SUCCESS"
    assert second.merge_result is not None
    assert second.merge_result.counters.rows_skipped == 0
    assert second.merge_result.counters.rows_inserted == 1

    with app_engine.begin() as connection:
        grade = connection.execute(select(StudentGrade)).one()
    assert grade.student_id == academic_student_id
    assert grade.grade == 30


def test_issue_becomes_resolved_once_the_student_resolves(
    app_engine: Engine, moodle_engine: Engine
) -> None:
    course_id, _ = _seed_unresolved(moodle_engine, app_engine)
    run_moodle_grades_sync(app_engine, moodle_engine, course_id)
    open_issue = _get_issue(app_engine)
    assert open_issue.status == "OPEN"
    assert open_issue.resolved_at is None

    seed_moodle_student_mapping(app_engine, MOODLE_USER_ID)
    outcome = run_moodle_grades_sync(app_engine, moodle_engine, course_id)

    assert outcome.status == "SUCCESS"
    resolved_issue = _get_issue(app_engine)
    assert resolved_issue.status == "RESOLVED"
    assert resolved_issue.resolved_at is not None
    assert resolved_issue.id == open_issue.id
