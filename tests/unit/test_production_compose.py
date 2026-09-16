"""Pins compose.prod.yml's established production contract so it can't
drift silently — see the README's "Production port convention" table.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _compose_prod_text() -> str:
    return (REPO_ROOT / "compose.prod.yml").read_text()


def test_production_compose_publishes_the_established_ports() -> None:
    content = _compose_prod_text()

    assert '"127.0.0.1:8080:8000"' in content, "API must publish host 8080 -> container 8000"
    assert '"127.0.0.1:5434:5432"' in content, "PostgreSQL must publish host 5434 -> container 5432"


def test_production_compose_never_binds_publicly() -> None:
    content = _compose_prod_text()

    assert "0.0.0.0" not in content


def test_production_compose_has_no_moodle_sync_service() -> None:
    """The Moodle sync runs natively via systemd in production — never
    as a Docker Compose service (see deploy/systemd/).
    """
    content = _compose_prod_text()

    assert "moodle-sync" not in content
    # A comment may legitimately explain that the API doesn't receive
    # this variable; there must be no actual env var assignment for it.
    assert "MOODLE_DB_URL:" not in content


def test_production_compose_never_builds_images() -> None:
    """Production only ever pulls prebuilt GHCR images."""
    content = _compose_prod_text()

    assert "build:" not in content
    assert "ghcr.io" in content
