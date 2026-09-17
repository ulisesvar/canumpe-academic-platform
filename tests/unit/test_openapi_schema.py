from app.main import app

EXPECTED_PATHS = (
    "/students/{student_id}/courses",
    "/students/{student_id}/attendance",
    "/students/{student_id}/grades",
    "/students/{student_id}/summary",
)


def test_all_phase_5_endpoints_appear_in_openapi() -> None:
    schema = app.openapi()

    for path in EXPECTED_PATHS:
        assert path in schema["paths"], f"missing OpenAPI path: {path}"
        assert "get" in schema["paths"][path]


def test_health_path_is_still_present() -> None:
    schema = app.openapi()

    assert "/health" in schema["paths"]
