import pytest
from sqlalchemy import Engine

from app.integration.moodle.errors import MoodleSourceIntegrityError
from app.integration.moodle.source import extract_moodle_batch
from tests.integration.moodle.fake_moodle import (
    enroll_student,
    ensure_cuenta_field,
    insert_course,
    insert_user,
    set_account_number,
)


def test_account_number_resolved_via_cuenta_shortname_not_fieldid_one(
    moodle_engine: Engine,
) -> None:
    """A decoy field occupies id=1, so this can only pass by looking up
    the field by shortname='cuenta' — never by assuming fieldid=1.
    """
    with moodle_engine.begin() as connection:
        cuenta_field_id = ensure_cuenta_field(connection)
        assert cuenta_field_id != 1, "test setup must not accidentally make cuenta field id 1"

        course_id = insert_course(connection, fullname="Algebra I")
        user_id = insert_user(connection, firstname="Ada", lastname="Lovelace")
        set_account_number(connection, user_id, cuenta_field_id, "1001")
        enroll_student(connection, userid=user_id, courseid=course_id)

    result = extract_moodle_batch(moodle_engine, course_id)

    assert len(result.students) == 1
    assert result.students[0].account_number == "1001"
    assert result.students[0].source_id == str(user_id)


def test_deleted_moodle_user_is_excluded(moodle_engine: Engine) -> None:
    with moodle_engine.begin() as connection:
        cuenta_field_id = ensure_cuenta_field(connection)
        course_id = insert_course(connection, fullname="Algebra I")

        active_user_id = insert_user(connection, firstname="Ada", lastname="Lovelace")
        set_account_number(connection, active_user_id, cuenta_field_id, "1001")
        enroll_student(connection, userid=active_user_id, courseid=course_id)

        deleted_user_id = insert_user(
            connection, firstname="Grace", lastname="Hopper", deleted=1
        )
        set_account_number(connection, deleted_user_id, cuenta_field_id, "1002")
        enroll_student(connection, userid=deleted_user_id, courseid=course_id)

    result = extract_moodle_batch(moodle_engine, course_id)

    assert [s.source_id for s in result.students] == [str(active_user_id)]


def test_inactive_user_enrolment_is_excluded(moodle_engine: Engine) -> None:
    with moodle_engine.begin() as connection:
        cuenta_field_id = ensure_cuenta_field(connection)
        course_id = insert_course(connection, fullname="Algebra I")

        user_id = insert_user(connection, firstname="Ada", lastname="Lovelace")
        set_account_number(connection, user_id, cuenta_field_id, "1001")
        enroll_student(connection, userid=user_id, courseid=course_id, enrolment_status=1)

    result = extract_moodle_batch(moodle_engine, course_id)

    assert result.students == []
    assert result.enrollments == []


def test_disabled_enrol_method_is_excluded(moodle_engine: Engine) -> None:
    with moodle_engine.begin() as connection:
        cuenta_field_id = ensure_cuenta_field(connection)
        course_id = insert_course(connection, fullname="Algebra I")

        user_id = insert_user(connection, firstname="Ada", lastname="Lovelace")
        set_account_number(connection, user_id, cuenta_field_id, "1001")
        enroll_student(connection, userid=user_id, courseid=course_id, enrol_status=1)

    result = extract_moodle_batch(moodle_engine, course_id)

    assert result.students == []
    assert result.enrollments == []


def test_configured_course_scope_is_enforced(moodle_engine: Engine) -> None:
    with moodle_engine.begin() as connection:
        cuenta_field_id = ensure_cuenta_field(connection)
        in_scope_course_id = insert_course(connection, fullname="Algebra I")
        other_course_id = insert_course(connection, fullname="Geometry")

        in_scope_user = insert_user(connection, firstname="Ada", lastname="Lovelace")
        set_account_number(connection, in_scope_user, cuenta_field_id, "1001")
        enroll_student(connection, userid=in_scope_user, courseid=in_scope_course_id)

        other_user = insert_user(connection, firstname="Grace", lastname="Hopper")
        set_account_number(connection, other_user, cuenta_field_id, "1002")
        enroll_student(connection, userid=other_user, courseid=other_course_id)

    result = extract_moodle_batch(moodle_engine, in_scope_course_id)

    assert [c.source_id for c in result.courses] == [str(in_scope_course_id)]
    assert [s.source_id for s in result.students] == [str(in_scope_user)]


def test_duplicate_account_number_fails_safely(moodle_engine: Engine) -> None:
    with moodle_engine.begin() as connection:
        cuenta_field_id = ensure_cuenta_field(connection)
        course_id = insert_course(connection, fullname="Algebra I")

        first_user = insert_user(connection, firstname="Ada", lastname="Lovelace")
        set_account_number(connection, first_user, cuenta_field_id, "1001")
        enroll_student(connection, userid=first_user, courseid=course_id)

        second_user = insert_user(connection, firstname="A.", lastname="L.")
        set_account_number(connection, second_user, cuenta_field_id, "1001")
        enroll_student(connection, userid=second_user, courseid=course_id)

    with pytest.raises(MoodleSourceIntegrityError):
        extract_moodle_batch(moodle_engine, course_id)
