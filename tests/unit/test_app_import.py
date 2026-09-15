def test_app_is_importable() -> None:
    from app.main import app

    assert app is not None


def test_settings_load_from_environment() -> None:
    from app.core.config import get_settings

    settings = get_settings()

    assert settings.database_url
    assert settings.environment
