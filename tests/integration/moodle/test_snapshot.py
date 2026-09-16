import pytest
from sqlalchemy import Engine, event

from app.integration.moodle import source as source_module
from app.integration.moodle.source import extract_moodle_batch
from tests.integration.moodle.fake_moodle import (
    enroll_student,
    ensure_cuenta_field,
    insert_course,
    insert_user,
    set_account_number,
)


def test_extraction_uses_a_repeatable_read_read_only_transaction(moodle_engine: Engine) -> None:
    with moodle_engine.begin() as connection:
        course_id = insert_course(connection, fullname="Algebra I")

    executed_statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        executed_statements.append(statement)

    event.listen(moodle_engine, "before_cursor_execute", _record)
    try:
        extract_moodle_batch(moodle_engine, course_id)
    finally:
        event.remove(moodle_engine, "before_cursor_execute", _record)

    isolation_statements = [s for s in executed_statements if "TRANSACTION ISOLATION LEVEL" in s]
    assert isolation_statements, "expected an explicit SET TRANSACTION ISOLATION LEVEL statement"
    assert "REPEATABLE READ" in isolation_statements[0]
    assert "READ ONLY" in isolation_statements[0]


def test_batch_uses_one_coherent_snapshot_across_all_three_queries(
    moodle_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A write committed by another connection *during* our extraction
    must not appear in any of the three queries — they all run inside
    the one transaction whose snapshot was fixed by its first statement.
    """
    with moodle_engine.begin() as connection:
        cuenta_field_id = ensure_cuenta_field(connection)
        course_id = insert_course(connection, fullname="Algebra I")
        first_user_id = insert_user(connection, firstname="Ada", lastname="Lovelace")
        set_account_number(connection, first_user_id, cuenta_field_id, "1001")
        enroll_student(connection, userid=first_user_id, courseid=course_id)

    original_fetch_courses = source_module._fetch_courses

    def patched_fetch_courses(connection, course_id_arg):
        with moodle_engine.begin() as other_connection:
            late_user_id = insert_user(other_connection, firstname="Grace", lastname="Hopper")
            set_account_number(other_connection, late_user_id, cuenta_field_id, "1002")
            enroll_student(other_connection, userid=late_user_id, courseid=course_id)
        return original_fetch_courses(connection, course_id_arg)

    monkeypatch.setattr(source_module, "_fetch_courses", patched_fetch_courses)

    result = extract_moodle_batch(moodle_engine, course_id)

    # The concurrently-committed second student/enrollment must not leak
    # into this batch, even though it was committed before the (later)
    # enrollments query ran.
    assert [s.source_id for s in result.students] == [str(first_user_id)]
    assert [e.student_source_id for e in result.enrollments] == [str(first_user_id)]
