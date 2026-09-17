"""Pins deploy/sql/academic_ingest_attendance_grants.example.sql to cover
every runtime object the Attendance sync actually touches, so a future
migration that adds a table/sequence can't silently outpace this
reference — the exact failure mode that let academic_ingest_attendance
reach production without access to integration.sync_issues (added by
0005_sync_issues after this file was first written) until a manual fix.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

REQUIRED_OBJECTS = (
    "raw_attendance",
    "staging",
    "integration.student_sources",
    "integration.course_sources",
    "integration.attendance_session_sources",
    "integration.attendance_record_sources",
    "integration.sync_runs",
    "integration.sync_state",
    "integration.sync_issues",
    "integration.sync_issues_id_seq",
    "academic.students",
    "academic.courses",
    "academic.attendance_sessions",
    "academic.attendance_records",
)


def _grants_text() -> str:
    return (
        REPO_ROOT / "deploy" / "sql" / "academic_ingest_attendance_grants.example.sql"
    ).read_text()


def test_grants_reference_mentions_every_required_runtime_object() -> None:
    content = _grants_text()

    for name in REQUIRED_OBJECTS:
        assert name in content, f"grants reference is missing {name}"


def test_grants_reference_covers_sync_issues_permissions() -> None:
    """The exact gap discovered in production: this role was created
    before 0005_sync_issues existed, so it had no access to the new
    table/sequence.
    """
    content = _grants_text()

    assert "GRANT SELECT, INSERT, UPDATE ON integration.sync_issues" in content
    assert "GRANT USAGE, SELECT ON SEQUENCE integration.sync_issues_id_seq" in content
