"""integration.sync_issues: makes an unresolved Attendance student's
skip observable and queryable instead of disappearing into a
rows_skipped counter — see app.integration.issues and
app.integration.attendance.merge.
"""

import time

from sqlalchemy import Engine, select

from app.integration.attendance.merge import STUDENT_SOURCE_ENTITY, UNRESOLVED_STUDENT_ISSUE_TYPE
from app.integration.attendance.sync import run_attendance_sync
from app.integration.models import SyncIssue
from tests.integration.attendance.fake_attendance import (
    insert_attendance,
    insert_session,
    insert_student,
)
from tests.integration.attendance.helpers import seed_academic_student, seed_moodle_course_mapping

MOODLE_COURSE_ID = 2
UNRESOLVED_ACCOUNT_NUMBER = "321167907"


def _seed_unresolved_student(app_engine: Engine, attendance_engine: Engine) -> int:
    seed_moodle_course_mapping(app_engine, MOODLE_COURSE_ID)
    with attendance_engine.begin() as connection:
        student_id = insert_student(connection, account_number=UNRESOLVED_ACCOUNT_NUMBER)
        session_id = insert_session(connection, status="OPEN")
        insert_attendance(connection, session_id=session_id, student_id=student_id)
    return student_id


def _get_issue(app_engine: Engine) -> SyncIssue:
    with app_engine.begin() as connection:
        issue = connection.execute(
            select(SyncIssue).where(SyncIssue.issue_type == UNRESOLVED_STUDENT_ISSUE_TYPE)
        ).one_or_none()
    assert issue is not None, "expected an UNRESOLVED_STUDENT sync_issues row"
    return issue


def test_unresolved_student_creates_one_open_issue(
    app_engine: Engine, attendance_engine: Engine
) -> None:
    student_id = _seed_unresolved_student(app_engine, attendance_engine)

    outcome = run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)

    assert outcome.status == "SUCCESS"
    issue = _get_issue(app_engine)
    assert issue.source_system == "attendance"
    assert issue.source_entity == STUDENT_SOURCE_ENTITY
    assert issue.source_id == str(student_id)
    assert issue.status == "OPEN"


def test_second_identical_sync_does_not_create_duplicate_issue(
    app_engine: Engine, attendance_engine: Engine
) -> None:
    _seed_unresolved_student(app_engine, attendance_engine)

    run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)
    run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)

    with app_engine.begin() as connection:
        issues = connection.execute(
            select(SyncIssue).where(SyncIssue.issue_type == UNRESOLVED_STUDENT_ISSUE_TYPE)
        ).all()
    assert len(issues) == 1


def test_first_seen_at_stays_unchanged_across_repeated_syncs(
    app_engine: Engine, attendance_engine: Engine
) -> None:
    _seed_unresolved_student(app_engine, attendance_engine)

    run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)
    original_first_seen_at = _get_issue(app_engine).first_seen_at

    time.sleep(0.01)
    run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)

    assert _get_issue(app_engine).first_seen_at == original_first_seen_at


def test_last_seen_at_advances_explicitly_on_each_sync(
    app_engine: Engine, attendance_engine: Engine
) -> None:
    _seed_unresolved_student(app_engine, attendance_engine)

    run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)
    original_last_seen_at = _get_issue(app_engine).last_seen_at

    time.sleep(0.01)
    run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)

    assert _get_issue(app_engine).last_seen_at > original_last_seen_at


def test_reference_value_contains_account_number(
    app_engine: Engine, attendance_engine: Engine
) -> None:
    _seed_unresolved_student(app_engine, attendance_engine)

    run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)

    assert _get_issue(app_engine).reference_value == UNRESOLVED_ACCOUNT_NUMBER


def test_issue_is_resolved_once_the_canonical_student_appears(
    app_engine: Engine, attendance_engine: Engine
) -> None:
    _seed_unresolved_student(app_engine, attendance_engine)
    run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)
    open_issue = _get_issue(app_engine)
    assert open_issue.status == "OPEN"
    assert open_issue.resolved_at is None

    seed_academic_student(app_engine, account_number=UNRESOLVED_ACCOUNT_NUMBER)
    outcome = run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)

    assert outcome.status == "SUCCESS"
    resolved_issue = _get_issue(app_engine)
    # 10. status becomes RESOLVED. 11. resolved_at is populated.
    assert resolved_issue.status == "RESOLVED"
    assert resolved_issue.resolved_at is not None
    # 12. same row retained (not deleted, not re-created).
    assert resolved_issue.id == open_issue.id
