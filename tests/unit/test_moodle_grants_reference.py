"""Pins the Moodle grants references (both the Academic-DB ingest
credential and the Moodle-side source credential) to cover every runtime
object the Moodle sync — including Phase 4 grades — actually touches, so
a future migration or query change can't silently outpace them. Same
philosophy as tests/unit/test_attendance_grants_reference.py: this is
exactly the failure mode that let academic_ingest_attendance reach
production without access to integration.sync_issues until a manual fix
(see that file's history) — never repeat it for academic_ingest_moodle.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

INGEST_REQUIRED_OBJECTS = (
    "raw_moodle.students",
    "raw_moodle.courses",
    "raw_moodle.enrollments",
    "raw_moodle.grade_items",
    "raw_moodle.student_grades",
    "staging.students",
    "staging.courses",
    "staging.enrollments",
    "staging.grade_items",
    "staging.student_grades",
    "integration.student_sources",
    "integration.course_sources",
    "integration.enrollment_sources",
    "integration.grade_item_sources",
    "integration.student_grade_sources",
    "integration.sync_runs",
    "integration.sync_state",
    "integration.sync_issues",
    "academic.students",
    "academic.courses",
    "academic.enrollments",
    "academic.grade_items",
    "academic.student_grades",
)

SOURCE_REQUIRED_OBJECTS = (
    "mdl_user",
    "mdl_user_info_field",
    "mdl_user_info_data",
    "mdl_course",
    "mdl_enrol",
    "mdl_user_enrolments",
    "mdl_grade_items",
    "mdl_grade_grades",
)


def _ingest_grants_text() -> str:
    return (
        REPO_ROOT / "deploy" / "sql" / "academic_ingest_moodle_grants.example.sql"
    ).read_text()


def _source_grants_text() -> str:
    return (REPO_ROOT / "deploy" / "sql" / "academic_sync_moodle_grants.example.sql").read_text()


def test_ingest_grants_reference_mentions_every_required_runtime_object() -> None:
    content = _ingest_grants_text()

    for name in INGEST_REQUIRED_OBJECTS:
        assert name in content, f"academic_ingest_moodle grants reference is missing {name}"


def test_ingest_grants_reference_never_uses_a_schema_wide_blanket_grant() -> None:
    """A schema-wide 'ALL TABLES/SEQUENCES IN SCHEMA x' grant only covers
    tables that exist at the moment it is run — it silently omits a table
    a later migration adds. Every actual GRANT statement must name its
    object explicitly; only the file's own explanatory comments (not
    checked here) may mention the pattern by name to say it's avoided.
    """
    grant_lines = [
        line.strip()
        for line in _ingest_grants_text().splitlines()
        if line.strip().upper().startswith("GRANT")
    ]
    assert grant_lines, "expected at least one GRANT statement"

    for line in grant_lines:
        assert "ALL TABLES" not in line.upper(), f"schema-wide table grant: {line!r}"
        assert "ALL SEQUENCES" not in line.upper(), f"schema-wide sequence grant: {line!r}"


def test_ingest_grants_reference_covers_grade_tables_and_sequences() -> None:
    content = _ingest_grants_text()

    assert "GRANT SELECT, INSERT ON raw_moodle.grade_items" in content
    assert "GRANT SELECT, INSERT ON raw_moodle.student_grades" in content
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON staging.grade_items" in content
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON staging.student_grades" in content
    assert "GRANT SELECT, INSERT, UPDATE ON integration.grade_item_sources" in content
    assert "GRANT SELECT, INSERT, UPDATE ON integration.student_grade_sources" in content
    assert "GRANT SELECT, INSERT, UPDATE ON integration.sync_issues" in content
    assert "GRANT SELECT, INSERT, UPDATE ON academic.grade_items" in content
    assert "GRANT SELECT, INSERT, UPDATE ON academic.student_grades" in content

    for sequence in (
        "raw_moodle.grade_items_id_seq",
        "raw_moodle.student_grades_id_seq",
        "staging.grade_items_id_seq",
        "staging.student_grades_id_seq",
        "integration.grade_item_sources_id_seq",
        "integration.student_grade_sources_id_seq",
        "integration.sync_issues_id_seq",
        "academic.grade_items_id_seq",
        "academic.student_grades_id_seq",
    ):
        assert sequence in content, f"missing sequence grant for {sequence}"


def test_source_grants_reference_mentions_every_required_moodle_table() -> None:
    content = _source_grants_text()

    for name in SOURCE_REQUIRED_OBJECTS:
        assert f"public.{name}" in content, (
            f"academic_sync_moodle grants reference is missing {name}"
        )


def test_source_grants_reference_covers_grade_tables() -> None:
    content = _source_grants_text()

    assert "GRANT SELECT ON public.mdl_grade_items" in content
    assert "GRANT SELECT ON public.mdl_grade_grades" in content


def test_source_grants_reference_is_select_only() -> None:
    """The Moodle source credential must never be granted write access —
    this pipeline only ever reads Moodle. Only actual GRANT statements
    are checked (not the file's own descriptive comments, which
    legitimately mention INSERT/UPDATE/DELETE to say they're absent).
    """
    grant_lines = [
        line.strip()
        for line in _source_grants_text().splitlines()
        if line.strip().upper().startswith("GRANT")
    ]
    assert grant_lines, "expected at least one GRANT statement"

    for line in grant_lines:
        for verb in ("INSERT", "UPDATE", "DELETE"):
            assert verb not in line.upper(), f"unexpected {verb} in source grant: {line!r}"
