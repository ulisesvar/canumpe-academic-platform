"""Unit tests for the account_number reconciliation decision itself.

academic.students.account_number has a UNIQUE constraint, so a real
academic.students table can never actually produce more than one match —
ambiguous resolution can't be constructed end-to-end against a real
database. _reconciliation_issue is the pure decision logic
validate_staged_batch calls with a real match count; testing it directly
is the meaningful way to prove "ambiguous still fails" without fighting
that constraint, and to document the three outcomes precisely.
"""

from app.integration.attendance.validation import _reconciliation_issue


def test_zero_matches_is_not_an_issue() -> None:
    """Unresolved (not yet in Moodle) is a SKIP, handled in merge.py —
    never a validation issue.
    """
    assert _reconciliation_issue("1001", 0) is None


def test_exactly_one_match_is_not_an_issue() -> None:
    assert _reconciliation_issue("1001", 1) is None


def test_more_than_one_match_is_a_blocking_issue() -> None:
    issue = _reconciliation_issue("1001", 2)

    assert issue is not None
    assert "1001" in issue
    assert "ambiguously" in issue
