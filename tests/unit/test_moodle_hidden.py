"""Moodle's `hidden` semantics — see
app.integration.moodle.grades_source.is_moodle_hidden.

mdl_grade_items.hidden and mdl_grade_grades.hidden are not booleans:
0 is visible, 1 is hidden always, and any other value is a Unix
timestamp meaning "hidden until" that time (Moodle:
grade_object::is_hidden — `hidden == 1 or (hidden != 0 and hidden > time())`).
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.integration.moodle.grades_source import is_moodle_hidden

REFERENCE = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
NOW = int(REFERENCE.timestamp())
ONE_DAY = 86_400


@pytest.mark.parametrize(
    ("hidden", "expected"),
    [
        (0, False),  # visible
        (None, False),  # NULL is treated as unset, i.e. visible
        (1, True),  # hidden always
        (NOW + 1, True),  # hidden until one second from now
        (NOW + ONE_DAY, True),  # hidden until tomorrow
        (NOW, False),  # the boundary second: no longer in the future, so visible
        (NOW - 1, False),  # hidden until a second ago
        (NOW - ONE_DAY, False),  # hidden until yesterday
        (2, False),  # a value above 1 is a timestamp (1970), never a flag
        (-5, False),  # never in the future, as in Moodle
    ],
)
def test_hidden_value_semantics(hidden: int | None, expected: bool) -> None:
    assert is_moodle_hidden(hidden, REFERENCE) is expected


def test_booleans_behave_as_zero_and_one() -> None:
    assert is_moodle_hidden(True, REFERENCE) is True
    assert is_moodle_hidden(False, REFERENCE) is False


def test_production_value_is_hidden_until_its_timestamp_then_visible() -> None:
    hidden_until = 1790737200  # 2026-09-30T03:00:00Z, seen on a real quiz item

    assert is_moodle_hidden(hidden_until, datetime(2026, 9, 30, 2, 59, 59, tzinfo=UTC)) is True
    assert is_moodle_hidden(hidden_until, datetime(2026, 9, 30, 3, 0, 1, tzinfo=UTC)) is False
    assert is_moodle_hidden(hidden_until, datetime(2026, 9, 30, 20, 0, tzinfo=UTC)) is False


def test_result_depends_on_the_instant_not_the_timezone_of_the_reference() -> None:
    plus_five = timezone(timedelta(hours=5))
    same_instant = REFERENCE.astimezone(plus_five)

    for hidden in (NOW - 1, NOW, NOW + 1):
        assert is_moodle_hidden(hidden, same_instant) == is_moodle_hidden(hidden, REFERENCE)


def test_a_naive_reference_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        is_moodle_hidden(NOW + ONE_DAY, datetime(2026, 9, 30, 12, 0))
