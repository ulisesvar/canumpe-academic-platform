"""An Attendance student whose account_number doesn't yet exist in
academic.students (Moodle hasn't created them) must be skipped, not
treated as a batch-failing error — see app.integration.attendance.merge
and validation for the rationale. This file exercises the full
production-shaped scenario: some students resolve, one doesn't, and a
later full sync picks up the unresolved one automatically once Moodle
creates it.
"""

from sqlalchemy import Engine, select

from app.academic.models import AttendanceRecord, Student
from app.integration.attendance.sync import run_attendance_sync
from app.integration.models import StudentSource
from tests.integration.attendance.fake_attendance import (
    insert_attendance,
    insert_session,
    insert_student,
)
from tests.integration.attendance.helpers import seed_academic_student, seed_moodle_course_mapping

MOODLE_COURSE_ID = 2
UNRESOLVED_ACCOUNT_NUMBER = "321167907"


def _seed_two_resolved_one_unresolved(
    app_engine: Engine, attendance_engine: Engine
) -> tuple[int, int, int]:
    """Two academic students exist (Moodle already synced them); a third
    Attendance student's account_number has no academic match yet.
    """
    seed_academic_student(app_engine, account_number="1001")
    seed_academic_student(app_engine, account_number="1002")
    seed_moodle_course_mapping(app_engine, MOODLE_COURSE_ID)

    with attendance_engine.begin() as connection:
        resolved_a = insert_student(connection, account_number="1001")
        resolved_b = insert_student(connection, account_number="1002")
        unresolved = insert_student(connection, account_number=UNRESOLVED_ACCOUNT_NUMBER)
        session_id = insert_session(connection, status="OPEN")
        insert_attendance(connection, session_id=session_id, student_id=resolved_a)
        insert_attendance(connection, session_id=session_id, student_id=resolved_b)
        insert_attendance(connection, session_id=session_id, student_id=unresolved)

    return resolved_a, resolved_b, unresolved


def test_unresolved_student_is_skipped_and_remaining_data_still_merges(
    app_engine: Engine, attendance_engine: Engine
) -> None:
    _resolved_a, _resolved_b, unresolved = _seed_two_resolved_one_unresolved(
        app_engine, attendance_engine
    )

    outcome = run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)

    # 1. Not fatal.
    assert outcome.status == "SUCCESS"
    assert outcome.merge_result is not None

    # 6. rows_skipped reflects both the skipped student and their record.
    assert outcome.merge_result.counters.rows_skipped == 2
    # 5. The two resolvable students + their records, plus the session,
    # still merge normally (2 student mappings + 1 session + 2 records).
    assert outcome.merge_result.counters.rows_inserted == 5

    with app_engine.begin() as connection:
        # 2. No academic student was created for the unresolved one.
        students = connection.execute(select(Student)).all()
        assert len(students) == 2
        assert {s.account_number for s in students} == {"1001", "1002"}

        # 3. No source mapping exists for the unresolved student.
        unresolved_mapping = connection.execute(
            select(StudentSource).where(
                StudentSource.source_system == "attendance",
                StudentSource.source_id == str(unresolved),
            )
        ).one_or_none()
        assert unresolved_mapping is None
        assert len(connection.execute(select(StudentSource)).all()) == 2

        # 4. Only the two resolvable students' attendance records exist.
        records = connection.execute(select(AttendanceRecord)).all()
        assert len(records) == 2


def test_later_sync_after_canonical_student_appears_imports_previously_skipped_history(
    app_engine: Engine, attendance_engine: Engine
) -> None:
    _resolved_a, _resolved_b, unresolved = _seed_two_resolved_one_unresolved(
        app_engine, attendance_engine
    )
    first = run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)
    assert first.status == "SUCCESS"
    assert first.merge_result is not None
    assert first.merge_result.counters.rows_skipped == 2

    with app_engine.begin() as connection:
        assert len(connection.execute(select(AttendanceRecord)).all()) == 2

    # Moodle sync (simulated) finally creates this student.
    newly_created_academic_id = seed_academic_student(
        app_engine, account_number=UNRESOLVED_ACCOUNT_NUMBER
    )

    second = run_attendance_sync(app_engine, attendance_engine, MOODLE_COURSE_ID)

    assert second.status == "SUCCESS"
    assert second.merge_result is not None
    # Nothing is skipped anymore; the previously-unresolved student's
    # mapping and their one attendance record are newly inserted.
    assert second.merge_result.counters.rows_skipped == 0
    assert second.merge_result.counters.rows_inserted == 2

    with app_engine.begin() as connection:
        mapping = connection.execute(
            select(StudentSource).where(
                StudentSource.source_system == "attendance",
                StudentSource.source_id == str(unresolved),
            )
        ).one()
        assert mapping.student_id == newly_created_academic_id

        records = connection.execute(select(AttendanceRecord)).all()
        assert len(records) == 3
        assert len(connection.execute(select(Student)).all()) == 3
