"""Pure, DB-free tests for 0-100 grade normalization — see
app.services.grade_normalization.normalize_score, the single formula
shared by the enriched /me/grades response and the evaluation engine.
"""

from decimal import Decimal

from app.services.grade_normalization import normalize_score


def test_75_of_100_normalizes_to_75() -> None:
    assert normalize_score(Decimal("75"), Decimal("100")) == Decimal("75")


def test_18_of_20_normalizes_to_90() -> None:
    assert normalize_score(Decimal("18"), Decimal("20")) == Decimal("90")


def test_0_of_100_normalizes_to_0_not_none() -> None:
    result = normalize_score(Decimal("0"), Decimal("100"))

    assert result == Decimal("0")
    assert result is not None


def test_null_grade_normalizes_to_none() -> None:
    assert normalize_score(None, Decimal("100")) is None


def test_zero_max_grade_never_divides_by_zero() -> None:
    """A real grade against a broken/zero max_grade must not raise —
    and must not produce a nonsensical score.
    """
    result = normalize_score(Decimal("50"), Decimal("0"))

    assert result is None


def test_negative_max_grade_is_handled_safely() -> None:
    result = normalize_score(Decimal("50"), Decimal("-10"))

    assert result is None


def test_none_max_grade_is_handled_safely() -> None:
    assert normalize_score(Decimal("50"), None) is None
