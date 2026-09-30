"""The attendance arithmetic in isolation — see
app.services.attendance_score_service.compute_attendance_score.
"""

from decimal import Decimal

from app.services.attendance_score_service import compute_attendance_score
from app.services.grade_normalization import round2


def test_no_closed_sessions_is_null_not_zero() -> None:
    score = compute_attendance_score(closed_sessions=0, present_sessions=0)

    assert score.closed_sessions == 0
    assert score.present_sessions == 0
    assert score.absent_sessions == 0
    assert score.score_100 is None


def test_eighteen_of_twenty_is_ninety() -> None:
    score = compute_attendance_score(closed_sessions=20, present_sessions=18)

    assert score.absent_sessions == 2
    assert score.score_100 == Decimal(90)


def test_all_absent_is_a_real_zero() -> None:
    score = compute_attendance_score(closed_sessions=4, present_sessions=0)

    assert score.absent_sessions == 4
    assert score.score_100 == Decimal(0)


def test_all_present_is_one_hundred() -> None:
    assert compute_attendance_score(closed_sessions=3, present_sessions=3).score_100 == Decimal(100)


def test_score_keeps_full_precision_until_rounded() -> None:
    score = compute_attendance_score(closed_sessions=3, present_sessions=2)

    assert score.score_100 is not None
    assert round2(score.score_100) == 66.67
    assert score.score_100 != Decimal("66.67")
