"""Shared 0–100 grade normalization and presentation rounding — the one
formula every grade-facing response in this API uses
(app.services.student_read_service's enriched /me/grades and
app.services.evaluation_service's breakdown), so it can never drift
between the two call sites. Deliberately dependency-free (no other
app.services import) to avoid a circular import between them.
"""

from decimal import ROUND_HALF_UP, Decimal

_DISPLAY_PRECISION = Decimal("0.01")


def normalize_score(grade: Decimal | None, max_grade: Decimal | None) -> Decimal | None:
    """(grade / max_grade) * 100. None when grade is None (not graded
    yet — never coerced to 0) or when max_grade is missing/non-positive
    (an invalid source max_grade is handled safely, never divided by).
    """
    if grade is None or max_grade is None or max_grade <= 0:
        return None
    return (grade / max_grade) * Decimal(100)


def round2(value: Decimal) -> float:
    return float(value.quantize(_DISPLAY_PRECISION, rounding=ROUND_HALF_UP))


def round2_or_none(value: Decimal | None) -> float | None:
    return round2(value) if value is not None else None
