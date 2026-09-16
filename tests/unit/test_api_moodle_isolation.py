from pathlib import Path

from app.core.config import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_api_settings_have_no_moodle_fields() -> None:
    """The public API must never be able to load Moodle credentials —
    they live only in app.integration.moodle.config.MoodleSyncSettings,
    which the API process never imports.
    """
    assert not any("moodle" in field_name for field_name in Settings.model_fields)


def test_main_module_source_does_not_reference_moodle() -> None:
    main_source = (REPO_ROOT / "app" / "main.py").read_text()

    assert "moodle" not in main_source.lower()
