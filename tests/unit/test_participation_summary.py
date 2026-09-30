"""The participation calculation in isolation — see
app.services.participation_service.summarize_participation.
"""

from decimal import Decimal

from app.services.grade_normalization import round2
from app.services.participation_service import summarize_participation


def test_no_observations_is_null_not_zero() -> None:
    summary = summarize_participation([])

    assert summary.count == 0
    assert summary.average is None
    assert summary.score_100 is None


def test_a_recorded_zero_is_a_real_zero() -> None:
    summary = summarize_participation([0])

    assert summary.count == 1
    assert summary.average == Decimal(0)
    assert summary.score_100 == Decimal(0)


def test_two_threes_average_three_and_score_100() -> None:
    summary = summarize_participation([3, 3])

    assert summary.average == Decimal(3)
    assert summary.score_100 == Decimal(100)


def test_the_number_of_observations_does_not_change_the_score() -> None:
    five = summarize_participation([3, 3, 3, 3, 3])
    two = summarize_participation([3, 3])

    assert five.average == two.average == Decimal(3)
    assert five.score_100 == two.score_100 == Decimal(100)


def test_three_two_three_three_averages_2_75_and_scores_91_67() -> None:
    summary = summarize_participation([3, 2, 3, 3])

    assert summary.average == Decimal("2.75")
    assert summary.score_100 is not None
    assert round2(summary.score_100) == 91.67


def test_score_is_computed_from_the_unrounded_average() -> None:
    summary = summarize_participation([1, 1, 2])  # average 4/3

    assert summary.average is not None and summary.score_100 is not None
    assert round2(summary.average) == 1.33
    assert round2(summary.score_100) == 44.44
