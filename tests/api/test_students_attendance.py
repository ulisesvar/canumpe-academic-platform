from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.api.helpers import (
    create_attendance_record,
    create_attendance_session,
    create_course,
    create_student,
)

T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


def test_attendance_endpoint_returns_canonical_records(
    client: TestClient, db_engine: Engine
) -> None:
    student_id = create_student(db_engine, account_number="7001")
    course_id = create_course(db_engine, name="Intro to Programming")
    session_id = create_attendance_session(db_engine, course_id=course_id, opened_at=T0)
    create_attendance_record(
        db_engine, attendance_session_id=session_id, student_id=student_id, recorded_at=T0
    )

    response = client.get(f"/students/{student_id}/attendance")

    assert response.status_code == 200
    body = response.json()
    assert body["student_id"] == student_id
    assert len(body["attendance"]) == 1
    event = body["attendance"][0]
    assert event["course_id"] == course_id
    assert event["session_id"] == session_id
    assert event["present"] is True


def test_unrelated_students_attendance_is_excluded(client: TestClient, db_engine: Engine) -> None:
    student_a = create_student(db_engine, account_number="7002")
    student_b = create_student(db_engine, account_number="7003")
    course_id = create_course(db_engine)
    session_id = create_attendance_session(db_engine, course_id=course_id, opened_at=T0)
    create_attendance_record(
        db_engine, attendance_session_id=session_id, student_id=student_a, recorded_at=T0
    )
    other_session = create_attendance_session(
        db_engine, course_id=course_id, opened_at=T0 + timedelta(hours=1)
    )
    create_attendance_record(
        db_engine, attendance_session_id=other_session, student_id=student_b, recorded_at=T0
    )

    response = client.get(f"/students/{student_a}/attendance")

    session_ids = [e["session_id"] for e in response.json()["attendance"]]
    assert session_ids == [session_id]


def test_endpoint_does_not_invent_absence_for_unrecorded_sessions(
    client: TestClient, db_engine: Engine
) -> None:
    """The student attended 2 of 3 sessions in the course. The response
    must contain exactly those 2 recorded events — never a synthesized
    third "absent" entry for the session with no record.
    """
    student_id = create_student(db_engine, account_number="7004")
    course_id = create_course(db_engine)
    attended_1 = create_attendance_session(db_engine, course_id=course_id, opened_at=T0)
    attended_2 = create_attendance_session(
        db_engine, course_id=course_id, opened_at=T0 + timedelta(days=1)
    )
    create_attendance_session(db_engine, course_id=course_id, opened_at=T0 + timedelta(days=2))
    create_attendance_record(
        db_engine, attendance_session_id=attended_1, student_id=student_id, recorded_at=T0
    )
    create_attendance_record(
        db_engine, attendance_session_id=attended_2, student_id=student_id, recorded_at=T0
    )

    response = client.get(f"/students/{student_id}/attendance")

    body = response.json()
    assert len(body["attendance"]) == 2
    assert all(event["present"] is True for event in body["attendance"])


def test_attendance_is_returned_in_chronological_order(
    client: TestClient, db_engine: Engine
) -> None:
    student_id = create_student(db_engine, account_number="7005")
    course_id = create_course(db_engine)
    sessions = []
    for offset in (3, 1, 2, 0, 4):
        session_id = create_attendance_session(
            db_engine, course_id=course_id, opened_at=T0 + timedelta(days=offset)
        )
        sessions.append((offset, session_id))
        create_attendance_record(
            db_engine, attendance_session_id=session_id, student_id=student_id, recorded_at=T0
        )
    expected_order = [session_id for _offset, session_id in sorted(sessions)]

    first = client.get(f"/students/{student_id}/attendance").json()
    second = client.get(f"/students/{student_id}/attendance").json()

    returned_order = [e["session_id"] for e in first["attendance"]]
    assert returned_order == expected_order
    assert first == second


def test_attendance_endpoint_returns_empty_list_for_student_with_no_records(
    client: TestClient, db_engine: Engine
) -> None:
    student_id = create_student(db_engine, account_number="7006")

    response = client.get(f"/students/{student_id}/attendance")

    assert response.status_code == 200
    assert response.json() == {"student_id": student_id, "attendance": []}
