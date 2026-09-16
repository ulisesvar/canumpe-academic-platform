from app.integration.moodle.hashing import course_hash, enrollment_hash, student_hash


def test_student_hash_is_deterministic_for_identical_content() -> None:
    first = student_hash("1001", "Ada", "Lovelace", "ada@example.com")
    second = student_hash("1001", "Ada", "Lovelace", "ada@example.com")

    assert first == second


def test_student_hash_changes_when_a_relevant_field_changes() -> None:
    original = student_hash("1001", "Ada", "Lovelace", "ada@example.com")
    changed = student_hash("1001", "Ada", "Lovelace-Byron", "ada@example.com")

    assert original != changed


def test_student_hash_treats_none_and_empty_string_as_normalized_equal() -> None:
    assert student_hash("1001", "Ada", "Lovelace", None) == student_hash(
        "1001", "Ada", "Lovelace", ""
    )


def test_course_hash_is_deterministic_and_change_sensitive() -> None:
    assert course_hash("CS101", "Intro", True) == course_hash("CS101", "Intro", True)
    assert course_hash("CS101", "Intro", True) != course_hash("CS101", "Intro", False)


def test_enrollment_hash_is_deterministic_and_change_sensitive() -> None:
    assert enrollment_hash("137", "2", "active") == enrollment_hash("137", "2", "active")
    assert enrollment_hash("137", "2", "active") != enrollment_hash("137", "2", "suspended")


def test_hash_does_not_collide_across_field_boundaries() -> None:
    """Without a field separator, ("ab", "c") and ("a", "bc") would hash
    the same by naive concatenation. They must not.
    """
    assert student_hash("ab", "c", "x", "y") != student_hash("a", "bc", "x", "y")
