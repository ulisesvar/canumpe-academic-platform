"""Phase 5 architecture boundary: the read API layer (routes, services,
repository) must never import a Moodle/Attendance source adapter, and
the repository must only ever query canonical academic.* models — never
integration.*/raw_moodle.*/raw_attendance.*/staging.*.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
API_LAYER_FILES = (
    REPO_ROOT / "app" / "api" / "routes" / "students.py",
    REPO_ROOT / "app" / "services" / "student_read_service.py",
    REPO_ROOT / "app" / "repositories" / "student_read_repository.py",
    REPO_ROOT / "app" / "main.py",
)


def _combined_source() -> str:
    return "\n".join(path.read_text() for path in API_LAYER_FILES)


def test_api_layer_never_imports_the_moodle_source_adapter() -> None:
    source = _combined_source()

    assert "app.integration.moodle" not in source
    assert "integration.moodle.source" not in source
    assert "integration.moodle.grades_source" not in source


def test_api_layer_never_imports_the_attendance_source_adapter() -> None:
    source = _combined_source()

    assert "app.integration.attendance" not in source


def test_repository_only_imports_canonical_academic_models() -> None:
    """Checks only actual import lines — the module's own docstring
    legitimately names the forbidden schemas to say they're avoided.
    """
    repository_source = (
        REPO_ROOT / "app" / "repositories" / "student_read_repository.py"
    ).read_text()
    import_lines = [
        line
        for line in repository_source.splitlines()
        if line.strip().startswith(("import ", "from "))
    ]

    assert any(line.startswith("from app.academic.models import") for line in import_lines)
    for forbidden in ("app.integration", "raw_moodle", "raw_attendance", "staging"):
        assert not any(forbidden in line for line in import_lines), forbidden
