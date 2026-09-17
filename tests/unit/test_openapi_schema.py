from app.main import app

EXPECTED_PATHS = (
    "/students/{student_id}/courses",
    "/students/{student_id}/attendance",
    "/students/{student_id}/grades",
    "/students/{student_id}/summary",
)

ME_PATHS = (
    "/me",
    "/me/courses",
    "/me/attendance",
    "/me/grades",
    "/me/summary",
)


def test_all_phase_5_endpoints_appear_in_openapi() -> None:
    schema = app.openapi()

    for path in EXPECTED_PATHS:
        assert path in schema["paths"], f"missing OpenAPI path: {path}"
        assert "get" in schema["paths"][path]


def test_health_path_is_still_present() -> None:
    schema = app.openapi()

    assert "/health" in schema["paths"]


def test_me_routes_document_api_key_security() -> None:
    schema = app.openapi()

    for path in ME_PATHS:
        security = schema["paths"][path]["get"].get("security")
        assert security, f"expected an API-key security requirement on {path}"


def test_admin_student_routes_document_api_key_security() -> None:
    schema = app.openapi()

    for path in EXPECTED_PATHS:
        security = schema["paths"][path]["get"].get("security")
        assert security, f"expected an API-key security requirement on {path}"


def test_health_does_not_require_api_key() -> None:
    schema = app.openapi()

    assert not schema["paths"]["/health"]["get"].get("security")
