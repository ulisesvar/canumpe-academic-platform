from datetime import UTC, datetime

from app.integration.attendance.hashing import (
    attendance_record_hash,
    attendance_session_hash,
    attendance_student_hash,
)

T1 = datetime(2026, 1, 1, tzinfo=UTC)
T2 = datetime(2026, 1, 2, tzinfo=UTC)


def test_student_hash_is_deterministic_and_change_sensitive() -> None:
    assert attendance_student_hash("1001") == attendance_student_hash("1001")
    assert attendance_student_hash("1001") != attendance_student_hash("1002")


def test_session_hash_is_deterministic_and_change_sensitive() -> None:
    assert attendance_session_hash(T1, None, "OPEN") == attendance_session_hash(T1, None, "OPEN")
    assert attendance_session_hash(T1, None, "OPEN") != attendance_session_hash(T1, T2, "CLOSED")


def test_record_hash_is_deterministic_and_change_sensitive() -> None:
    assert attendance_record_hash("11", "5", T1) == attendance_record_hash("11", "5", T1)
    assert attendance_record_hash("11", "5", T1) != attendance_record_hash("11", "5", T2)
