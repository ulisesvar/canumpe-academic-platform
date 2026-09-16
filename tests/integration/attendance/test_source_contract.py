import dataclasses

from sqlalchemy import Engine

from app.integration.attendance.source import (
    ExtractedAttendanceRecord,
    ExtractedAttendanceStudent,
    extract_attendance_batch,
)
from app.integration.attendance.validation import resolve_moodle_course_id
from tests.integration.attendance.fake_attendance import (
    insert_attendance,
    insert_session,
    insert_student,
)
from tests.integration.attendance.helpers import seed_moodle_course_mapping


def test_students_extracted_correctly(attendance_engine: Engine) -> None:
    with attendance_engine.begin() as connection:
        student_id = insert_student(connection, account_number="123456789")

    result = extract_attendance_batch(attendance_engine)

    assert len(result.students) == 1
    assert result.students[0].source_id == str(student_id)
    assert result.students[0].account_number == "123456789"


def test_sessions_extracted_correctly(attendance_engine: Engine) -> None:
    with attendance_engine.begin() as connection:
        session_id = insert_session(connection, status="CLOSED")

    result = extract_attendance_batch(attendance_engine)

    assert len(result.sessions) == 1
    assert result.sessions[0].source_id == str(session_id)
    assert result.sessions[0].status == "CLOSED"


def test_attendances_extracted_correctly(attendance_engine: Engine) -> None:
    with attendance_engine.begin() as connection:
        student_id = insert_student(connection, account_number="123456789")
        session_id = insert_session(connection)
        attendance_id = insert_attendance(connection, session_id=session_id, student_id=student_id)

    result = extract_attendance_batch(attendance_engine)

    assert len(result.attendances) == 1
    record = result.attendances[0]
    assert record.source_id == str(attendance_id)
    assert record.student_source_id == str(student_id)
    assert record.session_source_id == str(session_id)


def test_location_fields_are_not_ingested(attendance_engine: Engine) -> None:
    """The source row has latitude/longitude/distance_meters (NOT NULL in
    the real schema) — extraction must not carry them at all, not just
    happen to have nothing to carry.
    """
    with attendance_engine.begin() as connection:
        student_id = insert_student(connection, account_number="123456789")
        session_id = insert_session(connection)
        insert_attendance(
            connection,
            session_id=session_id,
            student_id=student_id,
            latitude=19.0,
            longitude=-99.0,
            distance_meters=42.0,
        )

    result = extract_attendance_batch(attendance_engine)

    record_field_names = {f.name for f in dataclasses.fields(ExtractedAttendanceRecord)}
    student_field_names = {f.name for f in dataclasses.fields(ExtractedAttendanceStudent)}
    forbidden = {"latitude", "longitude", "distance_meters", "telegram_username", "telegram_id"}

    assert not (record_field_names & forbidden)
    assert not (student_field_names & forbidden)
    assert len(result.attendances) == 1


def test_configured_course_mapping_is_required(app_engine: Engine) -> None:
    """Attendance has no course id of its own — the course is resolved
    through the existing Moodle course source mapping, never a hardcoded
    academic.courses.id. Missing mapping -> unresolved; present -> the
    correct canonical course id.
    """
    with app_engine.begin() as connection:
        assert resolve_moodle_course_id(connection, 2) is None

    academic_course_id = seed_moodle_course_mapping(app_engine, moodle_course_id=2)

    with app_engine.begin() as connection:
        assert resolve_moodle_course_id(connection, 2) == academic_course_id
        assert resolve_moodle_course_id(connection, 999) is None
