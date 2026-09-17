from app.integration.moodle.grades_hashing import grade_item_hash, student_grade_hash


def test_grade_item_hash_is_deterministic_and_change_sensitive() -> None:
    assert grade_item_hash("2", "Tarea 01", "assign", 100, False) == grade_item_hash(
        "2", "Tarea 01", "assign", 100, False
    )
    assert grade_item_hash("2", "Tarea 01", "assign", 100, False) != grade_item_hash(
        "2", "Tarea 01 (revisada)", "assign", 100, False
    )


def test_grade_item_hash_changes_when_max_grade_changes() -> None:
    assert grade_item_hash("2", "Tarea 01", "assign", 100, False) != grade_item_hash(
        "2", "Tarea 01", "assign", 50, False
    )


def test_grade_item_hash_changes_when_hidden_changes() -> None:
    assert grade_item_hash("2", "Tarea 01", "assign", 100, False) != grade_item_hash(
        "2", "Tarea 01", "assign", 100, True
    )


def test_student_grade_hash_is_deterministic_and_change_sensitive() -> None:
    assert student_grade_hash("5", "3", 30, False) == student_grade_hash("5", "3", 30, False)
    assert student_grade_hash("5", "3", 30, False) != student_grade_hash("5", "3", 80, False)


def test_student_grade_hash_distinguishes_null_from_zero() -> None:
    """NULL (not graded) and 0 (graded as zero) must never normalize to
    the same hash — see the README's NULL-vs-zero grade semantics.
    """
    assert student_grade_hash("5", "3", None, False) != student_grade_hash("5", "3", 0, False)
